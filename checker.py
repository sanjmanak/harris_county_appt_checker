#!/usr/bin/env python3
"""
Harris County Appointment Checker
Uses Playwright (headless browser) to check for available appointment slots.
Runs on GitHub Actions every 15 minutes. No API keys. No cost.

Approach:
1. Navigate to the appointment page
2. Click "Make Appointment" for the configured transaction type
3. Dismiss the initial info popup (OK button)
4. In the appointment form modal, select each branch from the dropdown
5. Click the date input to open the jQuery UI datepicker calendar
6. Read which dates are available (not red/disabled) from the calendar
7. Navigate to next month(s) and repeat
8. Email results
"""

import json
import os
import smtplib
import ssl
import sys
import html
from datetime import datetime, timezone
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeout


def load_config():
    config_path = os.path.join(os.path.dirname(__file__), "config.json")
    try:
        with open(config_path, "r") as f:
            return json.load(f)
    except FileNotFoundError:
        print("ERROR: config.json not found.")
        sys.exit(1)
    except json.JSONDecodeError as e:
        print(f"ERROR: config.json is not valid JSON: {e}")
        sys.exit(1)


def send_email(config, subject, text_body, html_body):
    """Send notification email via Gmail SMTP. Returns True on success."""
    sender = os.environ.get("EMAIL_ADDRESS", "").strip()
    password = os.environ.get("EMAIL_APP_PASSWORD", "").strip()
    recipient = os.environ.get("NOTIFY_EMAIL", "").strip()

    if not sender or not password or not recipient:
        print("ERROR: Missing or empty email environment variables.")
        print("Required: EMAIL_ADDRESS, EMAIL_APP_PASSWORD, NOTIFY_EMAIL")
        return False

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = sender
    msg["To"] = recipient
    msg.attach(MIMEText(text_body, "plain"))
    msg.attach(MIMEText(html_body, "html"))

    try:
        context = ssl.create_default_context()
        with smtplib.SMTP_SSL("smtp.gmail.com", 465, context=context, timeout=30) as server:
            server.login(sender, password)
            server.sendmail(sender, recipient, msg.as_string())
        print(f"Email sent to {recipient}")
        return True
    except smtplib.SMTPAuthenticationError:
        print("ERROR: Email login failed. Check EMAIL_ADDRESS and EMAIL_APP_PASSWORD.")
        return False
    except smtplib.SMTPException as e:
        print(f"ERROR: SMTP error: {e}")
        return False
    except OSError as e:
        print(f"ERROR: Network error sending email: {e}")
        return False


def build_found_email(config, available_slots, url):
    """Build email content for when slots are found."""
    subject = config.get("notify_subject", "Appointment Available!")
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")

    slots_text = "\n".join(
        f"  - {s['branch']} on {s['date']}"
        for s in available_slots
    )
    slots_html = "".join(
        f"<li><strong>{html.escape(s['branch'])}</strong> on {html.escape(s['date'])}</li>"
        for s in available_slots
    )

    text_body = f"""Appointment slots found!

{slots_text}

Book now: {url}
Checked at: {now}

---
To stop alerts, disable the workflow in your repo's Actions tab.
"""

    html_body = f"""<html>
<body style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto;">
    <div style="background: #10b981; color: white; padding: 20px; border-radius: 8px 8px 0 0;">
        <h1 style="margin: 0;">Appointment Slots Found!</h1>
    </div>
    <div style="padding: 20px; border: 1px solid #e5e7eb; border-top: none; border-radius: 0 0 8px 8px;">
        <ul>{slots_html}</ul>
        <p style="text-align: center; margin: 30px 0;">
            <a href="{html.escape(url)}"
               style="background: #10b981; color: white; padding: 14px 28px;
                      text-decoration: none; border-radius: 6px; font-size: 18px;">
                Book Now
            </a>
        </p>
        <p style="color: #6b7280; font-size: 12px;">
            Checked at {now}.
            To stop alerts, disable the workflow in your repo's Actions tab.
        </p>
    </div>
</body>
</html>"""

    return subject, text_body, html_body


def build_none_found_email(config, branches_checked, url):
    """Build email content for when no slots are found."""
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    branch_list = ", ".join(branches_checked)

    text_body = f"""No appointment slots found.

Checked branches: {branch_list}
Checked at: {now}

Will check again next run (every 15 minutes).
Book page: {url}
"""

    html_body = f"""<html>
<body style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto;">
    <div style="background: #6b7280; color: white; padding: 20px; border-radius: 8px 8px 0 0;">
        <h1 style="margin: 0;">No Appointments Found</h1>
    </div>
    <div style="padding: 20px; border: 1px solid #e5e7eb; border-top: none; border-radius: 0 0 8px 8px;">
        <p>Checked branches: {html.escape(branch_list)}</p>
        <p>Checked at: {now}</p>
        <p>Will check again next run (every 15 minutes).</p>
    </div>
</body>
</html>"""

    return "No Appointments Found", text_body, html_body


def get_available_dates_from_calendar(page):
    """
    Read the visible datepicker calendar and return available (non-red) dates.

    jQuery UI datepicker structure:
    - Available dates:   <td data-handler="selectDay"><a class="ui-state-default">5</a></td>
    - Unavailable dates: <td class="ui-datepicker-unselectable ui-state-disabled">
                           <span class="ui-state-default">12</span></td>

    Available dates have clickable <a> tags; unavailable have <span> tags.
    The month/year is in the calendar header (.ui-datepicker-title).
    """
    return page.evaluate("""() => {
        const picker = document.querySelector('.ui-datepicker');
        if (!picker || picker.style.display === 'none') return [];

        const titleEl = picker.querySelector('.ui-datepicker-title');
        if (!titleEl) return [];
        const monthYear = titleEl.textContent.trim();  // e.g. "April 2026"

        // Available dates have <a> tags inside td[data-handler="selectDay"]
        const available = [];
        const cells = picker.querySelectorAll('td[data-handler="selectDay"] a.ui-state-default');
        for (const cell of cells) {
            const day = cell.textContent.trim();
            if (day) {
                available.push(monthYear + ' ' + day);  // e.g. "April 2026 5"
            }
        }
        return available;
    }""")


def navigate_calendar_next_month(page):
    """Click the next-month arrow on the datepicker. Returns True if successful."""
    next_btn = page.query_selector(".ui-datepicker-next")
    if next_btn and next_btn.is_visible():
        # Check if it's disabled (no more months)
        classes = next_btn.get_attribute("class") or ""
        if "ui-state-disabled" in classes:
            return False
        next_btn.click()
        page.wait_for_timeout(1000)
        return True
    return False


def check_branch(page, branch_name, branch_selector, date_input_selector, months_to_check):
    """
    Select a branch, open the calendar, read available dates for each visible month,
    then navigate forward to check additional months.
    """
    print(f"\n  Selecting branch: {branch_name}")
    available = []

    try:
        # Select the branch
        page.select_option(branch_selector, label=branch_name)
        page.wait_for_timeout(2000)

        # Click the date input to open the datepicker calendar
        date_input = page.query_selector(date_input_selector)
        if not date_input:
            print(f"    ERROR: Date input not found ({date_input_selector})")
            return available

        date_input.click()
        page.wait_for_timeout(1500)

        # Verify the datepicker is visible
        picker = page.query_selector(".ui-datepicker")
        if not picker or not picker.is_visible():
            print(f"    ERROR: Datepicker did not open after clicking date input")
            return available

        # Check the current month and navigate forward
        for month_idx in range(months_to_check):
            dates = get_available_dates_from_calendar(page)
            if dates:
                print(f"    FOUND {len(dates)} available date(s): {dates}")
                for d in dates:
                    available.append({"branch": branch_name, "date": d})
            else:
                # Log which month had nothing
                month_label = page.evaluate("""() => {
                    const t = document.querySelector('.ui-datepicker-title');
                    return t ? t.textContent.trim() : 'unknown';
                }""")
                print(f"    No available dates in {month_label}")

            # Navigate to next month (if not the last iteration)
            if month_idx < months_to_check - 1:
                if not navigate_calendar_next_month(page):
                    print(f"    No more months to check")
                    break

    except PlaywrightTimeout:
        print(f"    Timeout while checking {branch_name}")
    except Exception as e:
        print(f"    Error with branch {branch_name}: {e}")

    return available


def find_element_by_candidates(page, candidates, description):
    """Try a list of selectors and return the first one that matches."""
    for sel in candidates:
        el = page.query_selector(sel)
        if el:
            print(f"  Found {description}: {sel}")
            return sel
    return None


def find_branch_dropdown(page, branches):
    """Find the branch dropdown by trying known selectors, then by content matching."""
    # Try known IDs first (ABranch confirmed from diagnostics), then common patterns
    candidates = [
        "#ABranch",
        "#ExistBranch", "#BranchId", "#Branch", "#branch",
        "#LocationId", "#Location",
    ]
    result = find_element_by_candidates(page, candidates, "branch dropdown")
    if result:
        return result

    # Fallback: find any <select> whose options contain a configured branch name
    print("  Known selectors not found, scanning all dropdowns...")
    selects = page.query_selector_all("select")
    for sel_el in selects:
        options_text = sel_el.evaluate(
            "el => Array.from(el.options).map(o => o.text.trim().toLowerCase())"
        )
        for branch in branches:
            if branch.lower() in options_text:
                sel_id = sel_el.get_attribute("id")
                sel_name = sel_el.get_attribute("name")
                selector = f"#{sel_id}" if sel_id else f"select[name='{sel_name}']"
                print(f"  Found branch dropdown by content match: {selector}")
                return selector

    return None


def find_date_input(page):
    """Find the date input field."""
    # DatePicker confirmed from diagnostics; try known IDs first
    candidates = [
        "#DatePicker",
        "#ExistDate", "#AppointmentDate", "#Date", "#date",
        "input.hasDatepicker",
        "input[placeholder*='Date']",
    ]
    return find_element_by_candidates(page, candidates, "date input")


def dump_page_state(page, label=""):
    """Log diagnostic info about the current page state."""
    prefix = f"[{label}] " if label else ""
    print(f"\n{prefix}--- Page Diagnostics ---")
    print(f"{prefix}URL: {page.url}")

    diagnostics = page.evaluate("""() => {
        const info = {};
        info.hasDatepicker = !!document.querySelector('.ui-datepicker');
        info.datepickerVisible = (() => {
            const dp = document.querySelector('.ui-datepicker');
            return dp ? dp.style.display !== 'none' && dp.offsetParent !== null : false;
        })();

        const selects = document.querySelectorAll('select');
        info.selects = Array.from(selects).map(s => ({
            id: s.id, name: s.name,
            optionCount: s.options.length,
            sampleOptions: Array.from(s.options).slice(0, 5).map(o => o.text.trim())
        }));

        const inputs = document.querySelectorAll('input[type="text"], input:not([type])');
        info.textInputs = Array.from(inputs).slice(0, 10).map(i => ({
            id: i.id, name: i.name,
            placeholder: i.placeholder,
            hasDatepickerClass: i.classList.contains('hasDatepicker')
        }));

        const dialogs = document.querySelectorAll('[role="dialog"], .modal, .ui-dialog');
        info.dialogCount = dialogs.length;
        info.visibleDialogs = Array.from(dialogs).filter(d => d.offsetParent !== null).length;

        return info;
    }""")

    for key, val in diagnostics.items():
        print(f"{prefix}{key}: {json.dumps(val, indent=2) if isinstance(val, (dict, list)) else val}")
    print(f"{prefix}--- End Diagnostics ---\n")


def main():
    print("=== Harris County Appointment Checker ===")
    print(f"=== {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')} ===\n")

    config = load_config()
    url = config["url"]
    branches = config.get("branches", [])
    transaction_type = config.get("transaction_type", "")
    months_to_check = config.get("months_to_check", 2)

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
            # Step 1: Load the appointment page
            print(f"Loading: {url}")
            page.goto(url, wait_until="networkidle", timeout=30000)
            page.wait_for_timeout(2000)

            # Step 2: Click "Make Appointment" for the transaction type
            print(f"Looking for transaction: {transaction_type}")
            clicked = False
            rows = page.query_selector_all("table tr")
            for row in rows:
                text = row.inner_text()
                if transaction_type.lower() in text.lower():
                    btn = row.query_selector("a, button, input[type='button'], input[type='submit']")
                    if btn:
                        btn.click()
                        page.wait_for_timeout(2000)
                        clicked = True
                        print(f"Clicked appointment button for: {transaction_type}")
                        break

            if not clicked:
                # Fallback: any "Make Appointment" link
                for link in page.query_selector_all("a"):
                    if "make appointment" in (link.inner_text() or "").lower():
                        link.click()
                        page.wait_for_timeout(2000)
                        clicked = True
                        print("Clicked generic 'Make Appointment' link")
                        break

            if not clicked:
                print("ERROR: Could not find 'Make Appointment' button")
                dump_page_state(page, "No button found")
                browser.close()
                sys.exit(1)

            # Step 3: Dismiss the initial info popup (click OK)
            # This is the first popup that appears - NOT the appointment form.
            # We only dismiss popups with "ok" text, not "close" (close would
            # dismiss the appointment form itself).
            for attempt in range(3):
                dismissed = False
                for btn in page.query_selector_all("button, input[type='button']"):
                    btn_text = (btn.inner_text() or btn.get_attribute("value") or "").strip().lower()
                    if btn_text == "ok" and btn.is_visible():
                        btn.click()
                        page.wait_for_timeout(1500)
                        print(f"Dismissed popup (clicked 'OK')")
                        dismissed = True
                        break
                if not dismissed:
                    break

            # Now we should be on the appointment form modal
            dump_page_state(page, "Appointment form")

            # Step 4: Find the branch dropdown and date input
            branch_selector = find_branch_dropdown(page, branches)
            if not branch_selector:
                print("ERROR: Could not find branch dropdown")
                dump_page_state(page, "No branch dropdown")
                page.screenshot(path="debug_no_branch.png")
                print("Saved debug screenshot: debug_no_branch.png")
                browser.close()
                sys.exit(1)

            date_input_selector = find_date_input(page)
            if not date_input_selector:
                print("ERROR: Could not find date input field")
                dump_page_state(page, "No date input")
                page.screenshot(path="debug_no_date.png")
                print("Saved debug screenshot: debug_no_date.png")
                browser.close()
                sys.exit(1)

            # Step 5: Check each branch
            for branch in branches:
                print(f"\nChecking branch: {branch}")
                slots = check_branch(
                    page, branch, branch_selector,
                    date_input_selector, months_to_check
                )
                all_available.extend(slots)

        except PlaywrightTimeout:
            print("ERROR: Page load timed out (30s)")
        except Exception as e:
            print(f"ERROR: {e}")
            import traceback
            traceback.print_exc()
        finally:
            browser.close()

    # Report results and send email
    print(f"\n{'='*50}")
    if all_available:
        total = len(all_available)
        print(f"FOUND {total} available date(s)!")
        for slot in all_available:
            print(f"  {slot['branch']} - {slot['date']}")

        subject, text_body, html_body = build_found_email(config, all_available, url)
        sent = send_email(config, subject, text_body, html_body)
        if not sent:
            print("\nWARNING: Failed to send notification email.")
    else:
        print("No appointments found.")
        subject, text_body, html_body = build_none_found_email(config, branches, url)
        sent = send_email(config, subject, text_body, html_body)
        if not sent:
            print("\nWARNING: Failed to send 'none found' email.")


if __name__ == "__main__":
    main()
