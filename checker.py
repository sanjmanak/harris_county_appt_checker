#!/usr/bin/env python3
"""
Harris County Appointment Checker

Drives a headless browser over the Harris County Tax Office auto-appointment
page, reads the jQuery UI datepicker for each configured branch, and emails you
when a slot opens up.

Flow:
  1. Load the appointment page
  2. Click "Make Appointment" for the configured transaction type
  3. Dismiss the info popup (OK button)
  4. For each branch: select it, open the calendar, read available days,
     step forward through N months
  5. Diff against the last run and email only what's new

Run locally:
  python checker.py --no-email                 # check, print, don't email
  python checker.py --url file:///.../page.html --no-email --no-state
"""

import argparse
import html
import json
import os
import re
import smtplib
import ssl
import sys
from datetime import date, datetime, timezone
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from playwright.sync_api import TimeoutError as PlaywrightTimeout
from playwright.sync_api import sync_playwright

try:
    from zoneinfo import ZoneInfo

    HOUSTON = ZoneInfo("America/Chicago")
except Exception:  # pragma: no cover - tzdata missing on some minimal images
    HOUSTON = timezone.utc

HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_STATE_PATH = os.path.join(HERE, ".state", "seen_slots.json")

MONTHS = [
    "January", "February", "March", "April", "May", "June",
    "July", "August", "September", "October", "November", "December",
]


# --------------------------------------------------------------------------
# Config
# --------------------------------------------------------------------------

def load_config(path=None):
    """Read and validate config.json. Exits with a clear message on problems."""
    config_path = path or os.path.join(HERE, "config.json")
    try:
        with open(config_path, "r") as f:
            config = json.load(f)
    except FileNotFoundError:
        sys.exit(f"ERROR: config file not found: {config_path}")
    except json.JSONDecodeError as e:
        sys.exit(f"ERROR: {config_path} is not valid JSON: {e}")

    if not isinstance(config, dict):
        sys.exit("ERROR: config.json must be a JSON object.")

    problems = []
    if not config.get("url"):
        problems.append("'url' is required")
    if not config.get("branches"):
        problems.append("'branches' must be a non-empty list of branch names")
    elif not isinstance(config["branches"], list):
        problems.append("'branches' must be a list")

    months = config.get("months_to_check", 2)
    if not isinstance(months, int) or isinstance(months, bool) or not 1 <= months <= 12:
        problems.append("'months_to_check' must be an integer between 1 and 12")

    if problems:
        sys.exit("ERROR: bad config.json:\n  - " + "\n  - ".join(problems))

    return config


# --------------------------------------------------------------------------
# Slot formatting helpers (pure functions -- covered by tests)
# --------------------------------------------------------------------------

def ordinal(day):
    """1 -> '1st', 2 -> '2nd', 11 -> '11th', 23 -> '23rd'."""
    day = int(day)
    if 10 <= day % 100 <= 20:
        suffix = "th"
    else:
        suffix = {1: "st", 2: "nd", 3: "rd"}.get(day % 10, "th")
    return f"{day}{suffix}"


def slot_key(slot):
    """Stable identity for a slot, used for de-duplication across runs."""
    return f"{slot['branch']}|{slot['iso']}"


def dedupe_and_sort(slots):
    """Drop duplicates and order by date, then branch name."""
    unique = {slot_key(s): s for s in slots}
    return sorted(unique.values(), key=lambda s: (s["iso"], s["branch"]))


def group_slots_by_month(slots):
    """Group sorted slots into an ordered {'April 2026': [slot, ...]} mapping."""
    grouped = {}
    for s in dedupe_and_sort(slots):
        grouped.setdefault(s["month_label"], []).append(s)
    return grouped


def summary_line(slots):
    """'April 2026: 3 slots | May 2026: 1 slot'"""
    parts = []
    for month, month_slots in group_slots_by_month(slots).items():
        n = len(month_slots)
        parts.append(f"{month}: {n} slot{'' if n == 1 else 's'}")
    return " | ".join(parts)


def now_local():
    return datetime.now(HOUSTON).strftime("%b %-d, %Y at %-I:%M %p %Z")


# --------------------------------------------------------------------------
# Run state (so you are not emailed about the same slot every 3 hours)
# --------------------------------------------------------------------------

def load_seen(path):
    try:
        with open(path, "r") as f:
            data = json.load(f)
        return set(data.get("seen", []))
    except (FileNotFoundError, json.JSONDecodeError, AttributeError):
        return set()


def save_seen(path, slots):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    payload = {
        "updated": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "seen": sorted(slot_key(s) for s in slots),
    }
    with open(path, "w") as f:
        json.dump(payload, f, indent=2)


def new_slots_only(slots, seen):
    return [s for s in dedupe_and_sort(slots) if slot_key(s) not in seen]


# --------------------------------------------------------------------------
# Email
# --------------------------------------------------------------------------

def send_email(subject, text_body, html_body):
    """Send via Gmail SMTP. Returns True on success."""
    sender = os.environ.get("EMAIL_ADDRESS", "").strip()
    password = os.environ.get("EMAIL_APP_PASSWORD", "").strip()
    recipient = os.environ.get("NOTIFY_EMAIL", "").strip()

    missing = [
        name for name, value in (
            ("EMAIL_ADDRESS", sender),
            ("EMAIL_APP_PASSWORD", password),
            ("NOTIFY_EMAIL", recipient),
        ) if not value
    ]
    if missing:
        print(f"ERROR: missing email secrets: {', '.join(missing)} -- skipping email.")
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
        print("ERROR: Gmail rejected the login. Check EMAIL_ADDRESS and EMAIL_APP_PASSWORD "
              "(it must be a 16-character App Password, not your account password).")
        return False
    except smtplib.SMTPException as e:
        print(f"ERROR: SMTP error: {e}")
        return False
    except OSError as e:
        print(f"ERROR: network error sending email: {e}")
        return False


def _shell(title, accent, body_html):
    return f"""<html>
<body style="font-family:-apple-system,Segoe UI,Arial,sans-serif;max-width:600px;margin:0 auto;">
  <div style="background:{accent};color:#fff;padding:22px;border-radius:8px 8px 0 0;">
    <h1 style="margin:0;font-size:22px;">{title}</h1>
  </div>
  <div style="padding:22px;border:1px solid #e5e7eb;border-top:none;border-radius:0 0 8px 8px;color:#111827;">
    {body_html}
  </div>
</body>
</html>"""


def build_found_email(config, slots, url):
    """Email for when slots are found, grouped by month."""
    subject = config.get("notify_subject", "Appointment Available!")
    stamp = now_local()
    by_month = group_slots_by_month(slots)

    text_lines = ["Appointment slots found!", "", summary_line(slots), ""]
    for month, month_slots in by_month.items():
        text_lines.append(f"{month}:")
        for s in month_slots:
            text_lines.append(f"  - {s['branch']} on the {ordinal(s['day'])}")
        text_lines.append("")
    text_lines += [
        f"Book now: {url}",
        f"Checked at {stamp}.",
        "",
        "---",
        "To stop alerts, disable the workflow in your repo's Actions tab.",
    ]

    badges = "".join(
        f'<span style="display:inline-block;background:rgba(255,255,255,.22);'
        f'padding:6px 14px;border-radius:20px;margin:6px 6px 0 0;font-size:14px;">'
        f'{html.escape(month)}: {len(ms)} slot{"" if len(ms) == 1 else "s"}</span>'
        for month, ms in by_month.items()
    )

    details = ""
    for month, month_slots in by_month.items():
        details += f'<h3 style="margin:18px 0 8px;color:#374151;">{html.escape(month)}</h3><ul style="margin:0;padding-left:20px;">'
        for s in month_slots:
            details += (f'<li style="margin:4px 0;"><strong>{html.escape(s["branch"])}</strong> '
                        f'on the {ordinal(s["day"])}</li>')
        details += "</ul>"

    body = f"""{details}
    <p style="text-align:center;margin:30px 0;">
      <a href="{html.escape(url, quote=True)}"
         style="background:#10b981;color:#fff;padding:14px 28px;text-decoration:none;
                border-radius:6px;font-size:18px;display:inline-block;">Book Now</a>
    </p>
    <p style="color:#6b7280;font-size:12px;">Checked at {html.escape(stamp)}.
       To stop alerts, disable the workflow in your repo's Actions tab.</p>"""

    header = f"""<h1 style="margin:0 0 6px;font-size:22px;">Appointment Slots Found!</h1><div>{badges}</div>"""
    html_body = f"""<html>
<body style="font-family:-apple-system,Segoe UI,Arial,sans-serif;max-width:600px;margin:0 auto;">
  <div style="background:#10b981;color:#fff;padding:22px;border-radius:8px 8px 0 0;">{header}</div>
  <div style="padding:22px;border:1px solid #e5e7eb;border-top:none;border-radius:0 0 8px 8px;color:#111827;">
    {body}
  </div>
</body>
</html>"""

    return subject, "\n".join(text_lines), html_body


def build_none_found_email(config, branches, url):
    stamp = now_local()
    branch_list = ", ".join(branches)
    text = (f"No appointment slots found.\n\nChecked branches: {branch_list}\n"
            f"Checked at {stamp}.\n\nBook page: {url}\n")
    html_body = _shell(
        "No Appointments Found", "#6b7280",
        f'<p>Checked branches: {html.escape(branch_list)}</p>'
        f'<p style="color:#6b7280;font-size:13px;">Checked at {html.escape(stamp)}.</p>',
    )
    return "No Appointments Found", text, html_body


def build_error_email(config, reason, url):
    """Sent when the check itself broke -- never confuse this with 'no slots'."""
    stamp = now_local()
    text = (f"The appointment checker could not complete its run.\n\nReason: {reason}\n"
            f"Time: {stamp}\n\nThe site layout may have changed. Check the GitHub Actions "
            f"log and the debug screenshot artifact.\n\nPage: {url}\n")
    html_body = _shell(
        "Checker Could Not Run", "#dc2626",
        f'<p>The run failed before it could read the calendar, so this is '
        f'<strong>not</strong> a "no appointments" result.</p>'
        f'<p><strong>Reason:</strong> {html.escape(str(reason))}</p>'
        f'<p style="color:#6b7280;font-size:13px;">{html.escape(stamp)} &middot; '
        f'Check the Actions log and the debug screenshot artifact.</p>',
    )
    return "Appointment Checker Error", text, html_body


# --------------------------------------------------------------------------
# Page interaction
# --------------------------------------------------------------------------

class CheckFailed(Exception):
    """Raised when the page did not look the way we expect."""


def parse_month_title(title):
    """'April 2026' -> (2026, 4). Returns None if unparseable."""
    m = re.search(r"([A-Za-z]+)\s+(\d{4})", title or "")
    if not m:
        return None
    name = m.group(1).strip().title()
    if name not in MONTHS:
        return None
    return int(m.group(2)), MONTHS.index(name) + 1


def read_visible_month(page):
    """
    Read the open jQuery UI datepicker.

    Available:   <td data-handler="selectDay"><a class="ui-state-default">5</a></td>
    Unavailable: <td class="ui-datepicker-unselectable ui-state-disabled"><span>12</span></td>

    Returns {"title": "April 2026", "days": [5, 9, 22]} or None if no calendar is open.
    """
    raw = page.evaluate("""() => {
        const pickers = Array.from(document.querySelectorAll('.ui-datepicker'));
        const picker = pickers.find(p => p.style.display !== 'none' && p.offsetParent !== null)
                    || pickers.find(p => p.style.display !== 'none');
        if (!picker) return null;
        const titleEl = picker.querySelector('.ui-datepicker-title');
        if (!titleEl) return null;
        const days = [];
        // Padding cells for adjacent months carry .ui-datepicker-other-month -- skip them.
        const cells = picker.querySelectorAll(
            'td[data-handler="selectDay"]:not(.ui-datepicker-other-month) a');
        for (const cell of cells) {
            const n = parseInt(cell.textContent.trim(), 10);
            if (!isNaN(n)) days.push(n);
        }
        return { title: titleEl.textContent.replace(/\\s+/g, ' ').trim(), days };
    }""")
    return raw


def close_calendar(page):
    """
    Collapse the datepicker so the next branch starts from a clean state.

    Never press Escape here: on the live site the form sits inside a Bootstrap
    modal, and an Escape that the datepicker does not swallow closes the whole
    modal -- after which every remaining branch times out on a hidden dropdown.
    """
    try:
        page.evaluate("""() => {
            if (window.jQuery && jQuery.datepicker) { try { jQuery.datepicker._hideDatepicker(); } catch (e) {} }
            document.querySelectorAll('.ui-datepicker').forEach(p => { p.style.display = 'none'; });
            if (document.activeElement && document.activeElement !== document.body) {
                document.activeElement.blur();
            }
        }""")
        page.wait_for_timeout(200)
    except Exception:
        pass


def resolve_branch_options(page, branch_selector, wanted):
    """
    Map the friendly names in config.json to the dropdown's real option values.

    The site labels options things like "Downtown (1001 Preston St)", so an exact
    label match fails. Match case-insensitively on substring in either direction.
    """
    options = page.evaluate(
        """sel => Array.from(document.querySelector(sel).options)
                    .map(o => ({ value: o.value, text: o.text.trim() }))""",
        branch_selector,
    )
    resolved, missing = [], []
    for name in wanted:
        needle = name.strip().lower()
        match = next(
            (o for o in options
             if o["text"] and o["value"]
             and (needle in o["text"].lower() or o["text"].lower() in needle)),
            None,
        )
        if match:
            resolved.append({"name": name, "value": match["value"], "text": match["text"]})
        else:
            missing.append(name)

    if missing:
        print(f"  WARNING: no dropdown option matched: {', '.join(missing)}")
        print(f"  Available options: {[o['text'] for o in options if o['value']]}")
    return resolved


def check_branch(page, branch, branch_selector, date_input_selector, months_to_check):
    """Select one branch and read `months_to_check` months of its calendar."""
    print(f"\nChecking branch: {branch['name']}  ({branch['text']})")
    found = []

    close_calendar(page)
    page.select_option(branch_selector, value=branch["value"])
    page.wait_for_timeout(1500)

    date_input = page.query_selector(date_input_selector)
    if not date_input:
        print(f"  ERROR: date input not found ({date_input_selector})")
        return found

    date_input.click()
    page.wait_for_timeout(1200)

    calendar = read_visible_month(page)
    if calendar is None:
        print("  ERROR: calendar did not open")
        return found

    seen_titles = set()
    for month_idx in range(months_to_check):
        calendar = read_visible_month(page)
        if calendar is None:
            break

        title = calendar["title"]
        if title in seen_titles:
            # The next-arrow did not actually advance; stop rather than double-count.
            print(f"  Calendar stopped advancing at {title}")
            break
        seen_titles.add(title)

        parsed = parse_month_title(title)
        for day in sorted(set(calendar["days"])):
            iso = (f"{parsed[0]:04d}-{parsed[1]:02d}-{day:02d}"
                   if parsed else f"9999-99-{day:02d}")
            found.append({
                "branch": branch["name"],
                "day": day,
                "month_label": title,
                "iso": iso,
            })

        if calendar["days"]:
            print(f"  FOUND in {title}: {sorted(set(calendar['days']))}")
        else:
            print(f"  Nothing open in {title}")

        if month_idx < months_to_check - 1 and not go_to_next_month(page):
            print("  No further months available")
            break

    close_calendar(page)
    return found


def go_to_next_month(page):
    """Click the datepicker's next-month arrow. False if it is unavailable."""
    btn = page.query_selector(".ui-datepicker-next")
    if not btn or not btn.is_visible():
        return False
    if "ui-state-disabled" in (btn.get_attribute("class") or ""):
        return False
    btn.click()
    page.wait_for_timeout(800)
    return True


def find_element_by_candidates(page, candidates, description):
    for sel in candidates:
        if page.query_selector(sel):
            print(f"  Found {description}: {sel}")
            return sel
    return None


def find_branch_dropdown(page, branches):
    """Known IDs first, then any <select> whose options mention a configured branch."""
    known = ["#ABranch", "#ExistBranch", "#BranchId", "#Branch", "#branch",
             "#LocationId", "#Location"]
    found = find_element_by_candidates(page, known, "branch dropdown")
    if found:
        return found

    print("  Known selectors missed, scanning every <select>...")
    for el in page.query_selector_all("select"):
        texts = el.evaluate("e => Array.from(e.options).map(o => o.text.trim().toLowerCase())")
        for branch in branches:
            needle = branch.lower()
            if any(needle in t or (t and t in needle) for t in texts):
                el_id = el.get_attribute("id")
                el_name = el.get_attribute("name")
                selector = f"#{el_id}" if el_id else f"select[name='{el_name}']"
                print(f"  Found branch dropdown by content match: {selector}")
                return selector
    return None


def find_date_input(page):
    return find_element_by_candidates(page, [
        "#DatePicker", "#ExistDate", "#AppointmentDate", "#Date", "#date",
        "input.hasDatepicker", "input[placeholder*='Date' i]",
    ], "date input")


def dump_page_state(page, label=""):
    prefix = f"[{label}] " if label else ""
    print(f"\n{prefix}--- page diagnostics ---")
    print(f"{prefix}URL: {page.url}")
    try:
        info = page.evaluate("""() => ({
            hasDatepicker: !!document.querySelector('.ui-datepicker'),
            selects: Array.from(document.querySelectorAll('select')).map(s => ({
                id: s.id, name: s.name, optionCount: s.options.length,
                sampleOptions: Array.from(s.options).slice(0, 6).map(o => o.text.trim())
            })),
            textInputs: Array.from(document.querySelectorAll('input[type="text"], input:not([type])'))
                .slice(0, 10).map(i => ({ id: i.id, name: i.name, placeholder: i.placeholder })),
            visibleDialogs: Array.from(document.querySelectorAll('[role="dialog"], .modal, .ui-dialog'))
                .filter(d => d.offsetParent !== null).length,
        })""")
        for key, value in info.items():
            rendered = json.dumps(value, indent=2) if isinstance(value, (dict, list)) else value
            print(f"{prefix}{key}: {rendered}")
    except Exception as e:
        print(f"{prefix}(diagnostics unavailable: {e})")
    print(f"{prefix}--- end diagnostics ---\n")


def open_appointment_form(page, transaction_type):
    """Click through the landing page into the branch/date form."""
    clicked = False
    for row in page.query_selector_all("table tr"):
        try:
            text = row.inner_text()
        except Exception:
            continue
        if transaction_type and transaction_type.lower() in text.lower():
            btn = row.query_selector("a, button, input[type='button'], input[type='submit']")
            if btn:
                btn.click()
                page.wait_for_timeout(2000)
                clicked = True
                print(f"Clicked appointment button for: {transaction_type}")
                break

    if not clicked:
        for link in page.query_selector_all("a, button"):
            try:
                label = (link.inner_text() or "").lower()
            except Exception:
                continue
            if "make appointment" in label:
                link.click()
                page.wait_for_timeout(2000)
                clicked = True
                print("Clicked generic 'Make Appointment' control")
                break

    if not clicked:
        raise CheckFailed(f"Could not find a 'Make Appointment' control for "
                          f"transaction type {transaction_type!r}")

    # Dismiss the informational popup. Only "OK" -- "Close" would kill the form.
    for _ in range(3):
        dismissed = False
        for btn in page.query_selector_all("button, input[type='button']"):
            try:
                label = (btn.inner_text() or btn.get_attribute("value") or "").strip().lower()
                if label == "ok" and btn.is_visible():
                    btn.click()
                    page.wait_for_timeout(1200)
                    print("Dismissed info popup (OK)")
                    dismissed = True
                    break
            except Exception:
                continue
        if not dismissed:
            break


def goto_with_retry(page, url, attempts=3):
    last = None
    for attempt in range(1, attempts + 1):
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=30000)
            page.wait_for_timeout(2000)
            return
        except PlaywrightTimeout as e:
            last = e
            print(f"  Load attempt {attempt}/{attempts} timed out, retrying...")
            page.wait_for_timeout(3000)
    raise CheckFailed(f"Page never loaded after {attempts} attempts: {last}")


def run_check(config, url, headless=True, screenshot_dir=HERE):
    """Returns the list of available slots. Raises CheckFailed on a broken run."""
    branches = config["branches"]
    months_to_check = config.get("months_to_check", 2)
    slots = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=headless)
        ctx = browser.new_context(
            viewport={"width": 1440, "height": 900},
            user_agent=("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"),
        )
        page = ctx.new_page()
        try:
            print(f"Loading: {url}")
            goto_with_retry(page, url)

            print(f"Looking for transaction: {config.get('transaction_type', '(any)')}")
            open_appointment_form(page, config.get("transaction_type", ""))

            branch_selector = find_branch_dropdown(page, branches)
            if not branch_selector:
                dump_page_state(page, "no branch dropdown")
                page.screenshot(path=os.path.join(screenshot_dir, "debug_no_branch.png"))
                raise CheckFailed("Branch dropdown not found -- the page layout may have changed.")

            date_input_selector = find_date_input(page)
            if not date_input_selector:
                dump_page_state(page, "no date input")
                page.screenshot(path=os.path.join(screenshot_dir, "debug_no_date.png"))
                raise CheckFailed("Date input not found -- the page layout may have changed.")

            resolved = resolve_branch_options(page, branch_selector, branches)
            if not resolved:
                dump_page_state(page, "no branches matched")
                page.screenshot(path=os.path.join(screenshot_dir, "debug_no_match.png"))
                raise CheckFailed("None of the configured branches matched the dropdown options.")

            for branch in resolved:
                try:
                    slots.extend(check_branch(page, branch, branch_selector,
                                              date_input_selector, months_to_check))
                except PlaywrightTimeout:
                    print(f"  Timed out on {branch['name']}, moving on")
                except Exception as e:
                    print(f"  Error on {branch['name']}: {e}")
                if not page.is_visible(branch_selector):
                    # The form itself went away. Partial results here would look
                    # like "nothing open" at the skipped branches, so fail loudly.
                    dump_page_state(page, "form closed")
                    page.screenshot(path=os.path.join(screenshot_dir, "debug_form_closed.png"))
                    raise CheckFailed(f"The appointment form closed after checking "
                                      f"{branch['name']} -- the remaining branches were not read.")
        finally:
            try:
                page.screenshot(path=os.path.join(screenshot_dir, "debug_last_state.png"))
            except Exception:
                pass
            browser.close()

    return dedupe_and_sort(slots)


# --------------------------------------------------------------------------
# Entry point
# --------------------------------------------------------------------------

def parse_args(argv=None):
    ap = argparse.ArgumentParser(description="Check Harris County auto appointment openings.")
    ap.add_argument("--config", default=None, help="path to config.json")
    ap.add_argument("--url", default=None, help="override the page URL (handy for local testing)")
    ap.add_argument("--no-email", action="store_true", help="print results, send nothing")
    ap.add_argument("--no-state", action="store_true", help="ignore and do not write the seen-slots file")
    ap.add_argument("--state-file", default=DEFAULT_STATE_PATH)
    ap.add_argument("--headful", action="store_true", help="show the browser window")
    ap.add_argument("--json", dest="json_out", default=None, help="also write results to this JSON file")
    return ap.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)
    print("=== Harris County Appointment Checker ===")
    print(f"=== {now_local()} ===\n")

    config = load_config(args.config)
    url = args.url or config["url"]
    branches = config["branches"]
    notify_when_none = bool(config.get("notify_when_none", False))
    only_new = bool(config.get("only_notify_on_new", True)) and not args.no_state

    try:
        slots = run_check(config, url, headless=not args.headful)
    except CheckFailed as e:
        print(f"\nCHECK FAILED: {e}")
        if not args.no_email:
            send_email(*build_error_email(config, e, url))
        return 2
    except Exception as e:  # unexpected -- still tell the user, still fail loudly
        import traceback
        traceback.print_exc()
        if not args.no_email:
            send_email(*build_error_email(config, f"{type(e).__name__}: {e}", url))
        return 2

    print("\n" + "=" * 52)
    if args.json_out:
        with open(args.json_out, "w") as f:
            json.dump(slots, f, indent=2)

    if not slots:
        print("No appointments found.")
        if not args.no_state:
            save_seen(args.state_file, [])
        if notify_when_none and not args.no_email:
            send_email(*build_none_found_email(config, branches, url))
        return 0

    print(f"FOUND {len(slots)} available date(s):")
    for s in slots:
        print(f"  {s['branch']:<20} {s['month_label']} {ordinal(s['day'])}")

    to_report = slots
    if only_new:
        seen = load_seen(args.state_file)
        to_report = new_slots_only(slots, seen)
        if not to_report:
            print("\nAll of these were already reported last run -- not emailing again.")

    if not args.no_state:
        save_seen(args.state_file, slots)

    if to_report and not args.no_email:
        subject, text_body, html_body = build_found_email(config, to_report, url)
        if not send_email(subject, text_body, html_body):
            print("\nWARNING: slots were found but the email did not send.")
            return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
