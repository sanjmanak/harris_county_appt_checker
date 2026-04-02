#!/usr/bin/env python3
"""
Harris County Appointment Checker
Uses Playwright (headless browser) to check for available appointment slots.
Runs on GitHub Actions every 15 minutes. No API keys. No cost.

Approach: Navigate to the appointment page, select each branch, and read the
calendar widget to find dates that aren't disabled/red (i.e., available).
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
    Read the visible calendar and return dates that are available (not disabled/red).

    jQuery UI datepicker marks:
    - Available dates: <td><a class="ui-state-default">15</a></td>
    - Unavailable dates: <td class="ui-datepicker-unselectable ui-state-disabled">
                            <span class="ui-state-default">15</span></td>

    So available dates have clickable <a> tags inside non-disabled <td> cells.
    We also grab the month/year from the calendar header.
    """
    results = page.evaluate("""() => {
        const available = [];

        // Handle both single and multi-month calendars
        const groups = document.querySelectorAll('.ui-datepicker-group, .ui-datepicker:not(.ui-datepicker-multi)');
        const containers = groups.length > 0 ? groups : [document.querySelector('.ui-datepicker')];

        for (const container of containers) {
            if (!container) continue;

            // Get month and year from the header
            const monthEl = container.querySelector('.ui-datepicker-month');
            const yearEl = container.querySelector('.ui-datepicker-year');
            if (!monthEl || !yearEl) continue;

            const month = monthEl.textContent.trim();
            const year = yearEl.textContent.trim();

            // Find all clickable (available) date cells
            const dateCells = container.querySelectorAll('td[data-handler="selectDay"] a.ui-state-default');
            for (const cell of dateCells) {
                const day = cell.textContent.trim();
                if (day) {
                    available.push(`${month} ${day}, ${year}`);
                }
            }
        }

        return available;
    }""")
    return results


def dump_page_state(page, label=""):
    """Log diagnostic info about the current page state."""
    prefix = f"[{label}] " if label else ""
    print(f"\n{prefix}--- Page Diagnostics ---")
    print(f"{prefix}URL: {page.url}")
    print(f"{prefix}Title: {page.title()}")

    diagnostics = page.evaluate("""() => {
        const info = {};

        // Check for datepicker
        info.hasDatepicker = !!document.querySelector('.ui-datepicker');
        info.hasDatepickerInline = !!document.querySelector('.ui-datepicker-inline');

        // Check for select/dropdown elements
        const selects = document.querySelectorAll('select');
        info.selects = Array.from(selects).map(s => ({
            id: s.id, name: s.name,
            optionCount: s.options.length,
            firstOptions: Array.from(s.options).slice(0, 5).map(o => o.text.trim())
        }));

        // Check for visible modals/dialogs
        const dialogs = document.querySelectorAll('[role="dialog"], .modal, .popup, .ui-dialog');
        info.dialogCount = dialogs.length;

        // Check for buttons
        const buttons = document.querySelectorAll('button, input[type="button"], input[type="submit"]');
        info.buttons = Array.from(buttons).slice(0, 10).map(b => ({
            text: (b.textContent || b.value || '').trim().substring(0, 50),
            visible: b.offsetParent !== null
        }));

        // Check for links with appointment-related text
        const links = document.querySelectorAll('a');
        info.appointmentLinks = Array.from(links)
            .filter(a => /appointment|book|schedule/i.test(a.textContent || ''))
            .map(a => ({text: a.textContent.trim().substring(0, 50), href: a.href}));

        // Check for calendar-related elements
        info.calendarElements = {
            uiDatepicker: document.querySelectorAll('.ui-datepicker').length,
            calendarTable: document.querySelectorAll('.ui-datepicker-calendar').length,
            availableDays: document.querySelectorAll('td[data-handler="selectDay"]').length,
            disabledDays: document.querySelectorAll('td.ui-datepicker-unselectable').length,
        };

        return info;
    }""")

    for key, val in diagnostics.items():
        print(f"{prefix}{key}: {json.dumps(val, indent=2) if isinstance(val, (dict, list)) else val}")
    print(f"{prefix}--- End Diagnostics ---\n")


def check_branch(page, branch_name, branch_dropdown_selector):
    """
    Select a branch from the dropdown, wait for the calendar to update,
    and return available dates.
    """
    print(f"\n  Selecting branch: {branch_name}")
    available = []

    try:
        page.select_option(branch_dropdown_selector, label=branch_name)
        # Wait for calendar to react to branch selection
        page.wait_for_timeout(3000)

        dates = get_available_dates_from_calendar(page)
        if dates:
            print(f"    FOUND {len(dates)} available date(s): {dates}")
            for d in dates:
                available.append({"branch": branch_name, "date": d})
        else:
            print(f"    No available dates on the calendar.")

    except PlaywrightTimeout:
        print(f"    Timeout selecting branch {branch_name}")
    except Exception as e:
        print(f"    Error with branch {branch_name}: {e}")

    return available


def main():
    print(f"=== Harris County Appointment Checker ===")
    print(f"=== {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')} ===\n")

    config = load_config()
    url = config["url"]
    branches = config.get("branches", [])
    transaction_type = config.get("transaction_type", "")

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
            # Step 1: Load the page
            print(f"Loading: {url}")
            page.goto(url, wait_until="networkidle", timeout=30000)
            page.wait_for_timeout(2000)

            dump_page_state(page, "After page load")

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
                # Fallback: look for any "Make Appointment" link
                links = page.query_selector_all("a")
                for link in links:
                    if "make appointment" in (link.inner_text() or "").lower():
                        link.click()
                        page.wait_for_timeout(2000)
                        clicked = True
                        print("Clicked generic 'Make Appointment' link")
                        break

            if not clicked:
                print("WARNING: Could not find 'Make Appointment' button")
                dump_page_state(page, "No button found")

            # Step 3: Dismiss any popups/modals (click OK/Close buttons)
            for attempt in range(3):
                ok_buttons = page.query_selector_all("button, input[type='button']")
                dismissed = False
                for btn in ok_buttons:
                    btn_text = (btn.inner_text() or btn.get_attribute("value") or "").strip().lower()
                    if btn_text in ("ok", "close", "accept", "continue", "i agree"):
                        if btn.is_visible():
                            btn.click()
                            page.wait_for_timeout(1500)
                            print(f"Dismissed dialog (clicked '{btn_text}')")
                            dismissed = True
                            break
                if not dismissed:
                    break

            dump_page_state(page, "After popups dismissed")

            # Step 4: Find the branch/location dropdown
            # Try common selectors - we'll log what we find
            branch_selector = None
            candidate_selectors = [
                "#ExistBranch",
                "#BranchId",
                "#Branch",
                "#LocationId",
                "#Location",
                "select[name*='branch' i]",
                "select[name*='location' i]",
            ]

            for sel in candidate_selectors:
                el = page.query_selector(sel)
                if el:
                    branch_selector = sel
                    print(f"Found branch dropdown: {sel}")
                    break

            if not branch_selector:
                # Fallback: find any select with options matching branch names
                print("Standard selectors not found, searching all dropdowns...")
                selects = page.query_selector_all("select")
                for sel_el in selects:
                    options_text = sel_el.evaluate("""el =>
                        Array.from(el.options).map(o => o.text.trim().toLowerCase())
                    """)
                    # Check if any configured branch appears in this dropdown
                    for branch in branches:
                        if branch.lower() in options_text:
                            sel_id = sel_el.get_attribute("id")
                            sel_name = sel_el.get_attribute("name")
                            branch_selector = f"#{sel_id}" if sel_id else f"select[name='{sel_name}']"
                            print(f"Found branch dropdown by content match: {branch_selector}")
                            break
                    if branch_selector:
                        break

            if not branch_selector:
                print("ERROR: Could not find branch/location dropdown on the page.")
                dump_page_state(page, "No dropdown found")
                # Take a screenshot for debugging
                page.screenshot(path="debug_screenshot.png")
                print("Saved debug screenshot to debug_screenshot.png")
                browser.close()
                sys.exit(1)

            # Step 5: Check each branch
            for branch in branches:
                print(f"\nChecking branch: {branch}")
                slots = check_branch(page, branch, branch_selector)
                all_available.extend(slots)

        except PlaywrightTimeout:
            print("ERROR: Page load timed out (30s)")
        except Exception as e:
            print(f"ERROR: {e}")
            import traceback
            traceback.print_exc()
        finally:
            browser.close()

    # Report results
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
