#!/usr/bin/env python3
"""
Harris County Appointment Checker
Uses Playwright (headless browser) to check for available appointment slots.
Runs on GitHub Actions every 15 minutes. No API keys. No cost.
"""

import json
import os
import smtplib
import ssl
import sys
from datetime import datetime, timezone, timedelta
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeout


def load_config():
    config_path = os.path.join(os.path.dirname(__file__), "config.json")
    with open(config_path, "r") as f:
        return json.load(f)


def send_email(config, available_slots, url):
    """Send notification email via Gmail SMTP."""
    sender = os.environ.get("EMAIL_ADDRESS")
    password = os.environ.get("EMAIL_APP_PASSWORD")
    recipient = os.environ.get("NOTIFY_EMAIL")

    if not all([sender, password, recipient]):
        print("ERROR: Missing email environment variables.")
        print("Required: EMAIL_ADDRESS, EMAIL_APP_PASSWORD, NOTIFY_EMAIL")
        return False

    subject = config.get("notify_subject", "Appointment Available!")

    slots_text = "\n".join(
        f"  - {s['branch']} on {s['date']}: {', '.join(s['times'])}"
        for s in available_slots
    )
    slots_html = "".join(
        f"<li><strong>{s['branch']}</strong> on {s['date']}: {', '.join(s['times'])}</li>"
        for s in available_slots
    )

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = sender
    msg["To"] = recipient

    text_body = f"""
Appointment slots found!

{slots_text}

Book now: {url}
Checked at: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}

---
To stop alerts, disable the workflow in your repo's Actions tab.
"""

    html_body = f"""
<html>
<body style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto;">
    <div style="background: #10b981; color: white; padding: 20px; border-radius: 8px 8px 0 0;">
        <h1 style="margin: 0;">Appointment Slots Found!</h1>
    </div>
    <div style="padding: 20px; border: 1px solid #e5e7eb; border-top: none; border-radius: 0 0 8px 8px;">
        <ul>{slots_html}</ul>
        <p style="text-align: center; margin: 30px 0;">
            <a href="{url}"
               style="background: #10b981; color: white; padding: 14px 28px;
                      text-decoration: none; border-radius: 6px; font-size: 18px;">
                Book Now
            </a>
        </p>
        <p style="color: #6b7280; font-size: 12px;">
            Checked at {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}.
            To stop alerts, disable the workflow in your repo's Actions tab.
        </p>
    </div>
</body>
</html>
"""

    msg.attach(MIMEText(text_body, "plain"))
    msg.attach(MIMEText(html_body, "html"))

    try:
        context = ssl.create_default_context()
        with smtplib.SMTP_SSL("smtp.gmail.com", 465, context=context) as server:
            server.login(sender, password)
            server.sendmail(sender, recipient, msg.as_string())
        print(f"Email sent to {recipient}")
        return True
    except Exception as e:
        print(f"Failed to send email: {e}")
        return False


def check_branch(page, branch_name, config):
    """
    Select a branch, then scan the next N days for any available time slots.
    Returns a list of {branch, date, times} dicts.
    """
    days_to_check = config.get("days_to_check", 30)
    available = []

    print(f"  Selecting branch: {branch_name}")

    try:
        # Select the branch from the dropdown
        page.select_option("#ExistBranch", label=branch_name)
        page.wait_for_timeout(2000)

        datepicker = page.query_selector("#ExistDate")
        if not datepicker:
            print(f"  Could not find date picker for {branch_name}")
            return available

        datepicker.click()
        page.wait_for_timeout(1000)

        today = datetime.now()

        for day_offset in range(1, days_to_check + 1):
            check_date = today + timedelta(days=day_offset)
            date_str = check_date.strftime("%m/%d/%Y")

            try:
                page.evaluate(f"""
                    const input = document.querySelector('#ExistDate');
                    if (input) {{
                        input.value = '{date_str}';
                        input.dispatchEvent(new Event('change', {{ bubbles: true }}));
                    }}
                """)
                page.wait_for_timeout(1500)

                time_options = page.evaluate("""
                    const select = document.querySelector('#ExistTime');
                    if (!select) return [];
                    return Array.from(select.options)
                        .filter(o => o.value && o.value !== '' && !o.disabled)
                        .map(o => o.text.trim())
                        .filter(t => t !== '' && !t.toLowerCase().includes('select'));
                """)

                if time_options:
                    print(f"    FOUND slots on {date_str}: {time_options}")
                    available.append({
                        "branch": branch_name,
                        "date": date_str,
                        "times": time_options
                    })
                else:
                    print(f"    No slots on {date_str}")

            except Exception as e:
                print(f"    Error checking {date_str}: {e}")
                continue

    except Exception as e:
        print(f"  Error with branch {branch_name}: {e}")

    return available


def main():
    print(f"=== Harris County Appointment Checker ===")
    print(f"=== {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')} ===\n")

    config = load_config()
    url = config["url"]
    branches = config.get("branches", [])
    transaction_type = config.get("transaction_type", "New Resident (First time TX registration)")

    if not branches:
        print("ERROR: No branches configured in config.json")
        sys.exit(1)

    all_available = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        ctx = browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            )
        )
        page = ctx.new_page()

        try:
            print(f"Loading: {url}")
            page.goto(url, wait_until="networkidle", timeout=30000)
            page.wait_for_timeout(3000)

            # Click the "Make Appointment" button for the transaction type
            print(f"Looking for transaction: {transaction_type}")

            rows = page.query_selector_all("table tr")
            clicked = False
            for row in rows:
                text = row.inner_text()
                if transaction_type.lower() in text.lower():
                    btn = row.query_selector("a, button, input[type='button']")
                    if btn:
                        btn.click()
                        page.wait_for_timeout(2000)
                        clicked = True
                        print(f"Clicked appointment button for: {transaction_type}")
                        break

            if not clicked:
                links = page.query_selector_all("a")
                for link in links:
                    if "make appointment" in (link.inner_text() or "").lower():
                        link.click()
                        page.wait_for_timeout(2000)
                        clicked = True
                        print("Clicked generic Make Appointment link")
                        break

            # Dismiss any info popup
            ok_buttons = page.query_selector_all("button")
            for btn in ok_buttons:
                if (btn.inner_text() or "").strip().lower() == "ok":
                    if btn.is_visible():
                        btn.click()
                        page.wait_for_timeout(1000)
                        print("Dismissed info dialog")
                        break

            # Check each configured branch
            for branch in branches:
                print(f"\nChecking branch: {branch}")
                slots = check_branch(page, branch, config)
                all_available.extend(slots)

        except PlaywrightTimeout:
            print("Page load timed out")
        except Exception as e:
            print(f"Error: {e}")
        finally:
            browser.close()

    print(f"\n{'='*50}")
    if all_available:
        total_slots = sum(len(s["times"]) for s in all_available)
        print(f"FOUND {total_slots} available slot(s) across {len(all_available)} date(s)!")
        for slot in all_available:
            print(f"  {slot['branch']} - {slot['date']}: {', '.join(slot['times'])}")

        sent = send_email(config, all_available, url)
        if sent:
            print("\nNotification sent!")
        else:
            print("\nFailed to send notification.")
            sys.exit(1)
    else:
        print("No appointments found. Will check again next run.")


if __name__ == "__main__":
    main()
