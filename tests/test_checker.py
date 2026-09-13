"""
Tests for the appointment checker.

Pure-function tests run anywhere. The browser tests drive checker.py against
tests/fixtures/mock_appointment_page.html -- a local replica of the DOM shape
the real page uses -- so the scraping logic is exercised without hitting
hctax.net. Run them with:  python -m pytest tests -v
"""

import json
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import checker  # noqa: E402

FIXTURE = "file://" + os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "fixtures", "mock_appointment_page.html"
)

playwright_installed = pytest.importorskip if False else None
try:
    from playwright.sync_api import sync_playwright  # noqa: F401
    HAS_BROWSER = True
except ImportError:  # pragma: no cover
    HAS_BROWSER = False


def slot(branch, iso, day, label):
    return {"branch": branch, "iso": iso, "day": day, "month_label": label}


# --------------------------------------------------------------------------
# Pure functions
# --------------------------------------------------------------------------

@pytest.mark.parametrize("day,expected", [
    (1, "1st"), (2, "2nd"), (3, "3rd"), (4, "4th"),
    (11, "11th"), (12, "12th"), (13, "13th"),
    (21, "21st"), (22, "22nd"), (23, "23rd"), (30, "30th"), (31, "31st"),
])
def test_ordinal_suffixes(day, expected):
    assert checker.ordinal(day) == expected


def test_dedupe_and_sort_orders_chronologically_across_branches():
    slots = [
        slot("Spring Branch", "2026-05-03", 3, "May 2026"),
        slot("Downtown", "2026-04-21", 21, "April 2026"),
        slot("Downtown", "2026-04-07", 7, "April 2026"),
        slot("Downtown", "2026-04-07", 7, "April 2026"),  # duplicate
    ]
    out = checker.dedupe_and_sort(slots)
    assert [s["iso"] for s in out] == ["2026-04-07", "2026-04-21", "2026-05-03"]


def test_group_by_month_is_chronological_even_when_later_branch_has_earlier_month():
    slots = [
        slot("Spring Branch", "2026-05-11", 11, "May 2026"),
        slot("Downtown", "2026-04-07", 7, "April 2026"),
    ]
    assert list(checker.group_slots_by_month(slots)) == ["April 2026", "May 2026"]


def test_summary_line_pluralization():
    slots = [
        slot("Downtown", "2026-04-07", 7, "April 2026"),
        slot("Downtown", "2026-04-21", 21, "April 2026"),
        slot("Spring Branch", "2026-05-03", 3, "May 2026"),
    ]
    assert checker.summary_line(slots) == "April 2026: 2 slots | May 2026: 1 slot"


def test_parse_month_title():
    assert checker.parse_month_title("April 2026") == (2026, 4)
    assert checker.parse_month_title("  December   2027 ") == (2027, 12)
    assert checker.parse_month_title("Smarch 2026") is None
    assert checker.parse_month_title("") is None


def test_new_slots_only_filters_already_seen():
    a = slot("Downtown", "2026-04-07", 7, "April 2026")
    b = slot("Downtown", "2026-04-21", 21, "April 2026")
    assert checker.new_slots_only([a, b], {checker.slot_key(a)}) == [b]
    assert checker.new_slots_only([a, b], set()) == [a, b]


def test_state_roundtrip(tmp_path):
    path = str(tmp_path / "state" / "seen.json")
    a = slot("Downtown", "2026-04-07", 7, "April 2026")
    checker.save_seen(path, [a])
    assert checker.load_seen(path) == {"Downtown|2026-04-07"}


def test_load_seen_tolerates_missing_or_corrupt_file(tmp_path):
    assert checker.load_seen(str(tmp_path / "nope.json")) == set()
    bad = tmp_path / "bad.json"
    bad.write_text("{not json")
    assert checker.load_seen(str(bad)) == set()


# --------------------------------------------------------------------------
# Email bodies
# --------------------------------------------------------------------------

CONFIG = {"notify_subject": "Slot!", "branches": ["Downtown"], "url": "https://example.test"}


def test_found_email_uses_correct_ordinals_and_escapes_html():
    slots = [
        slot("Downtown & Co", "2026-04-01", 1, "April 2026"),
        slot("Downtown & Co", "2026-04-22", 22, "April 2026"),
    ]
    subject, text, html_body = checker.build_found_email(CONFIG, slots, CONFIG["url"])
    assert subject == "Slot!"
    assert "on the 1st" in text and "on the 22nd" in text
    assert "1th" not in text and "22th" not in text
    assert "Downtown &amp; Co" in html_body  # escaped, not raw &
    assert "April 2026: 2 slots" in text


def test_error_email_is_clearly_not_a_no_slots_result():
    subject, text, html_body = checker.build_error_email(
        CONFIG, "Branch dropdown not found", CONFIG["url"])
    assert subject == "Appointment Checker Error"
    assert "not" in html_body and "no appointments" in html_body.lower()
    assert "Branch dropdown not found" in text


def test_config_validation_rejects_bad_values(tmp_path):
    bad = tmp_path / "config.json"
    bad.write_text(json.dumps({"branches": ["Downtown"], "months_to_check": 0}))
    with pytest.raises(SystemExit) as exc:
        checker.load_config(str(bad))
    message = str(exc.value)
    assert "'url' is required" in message
    assert "months_to_check" in message


def test_config_accepts_the_shipped_config():
    config = checker.load_config(
        os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "config.json"))
    assert config["url"].startswith("https://")
    assert config["branches"]


# --------------------------------------------------------------------------
# Browser-driven tests against the local fixture
# --------------------------------------------------------------------------

pytestmark_browser = pytest.mark.skipif(not HAS_BROWSER, reason="playwright not installed")


@pytest.fixture
def page():
    """Function-scoped: run_check() opens its own sync_playwright, which cannot
    nest inside a still-running one."""
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        pg = browser.new_page()
        yield pg
        browser.close()


@pytestmark_browser
def test_fuzzy_branch_matching_against_verbose_option_text(page):
    """config says 'Downtown'; the option says 'Downtown (1001 Preston St)'."""
    page.goto(FIXTURE)
    checker.open_appointment_form(page, "New Resident (First time TX registration)")
    resolved = checker.resolve_branch_options(
        page, "#ABranch", ["Downtown", "Burnett Bayland", "Not A Real Branch"])
    assert [r["name"] for r in resolved] == ["Downtown", "Burnett Bayland"]
    assert resolved[0]["value"] == "1"
    assert resolved[1]["value"] == "2"


@pytestmark_browser
def test_calendar_read_ignores_red_and_other_month_cells(page):
    page.goto(FIXTURE)
    checker.open_appointment_form(page, "New Resident (First time TX registration)")
    page.select_option("#ABranch", value="1")
    page.click("#DatePicker")
    calendar = checker.read_visible_month(page)
    assert calendar["title"] == "April 2026"
    # Fixture opens the 7th and 21st only; padding cells show 28/29/30 and must not leak.
    assert calendar["days"] == [7, 21]


@pytestmark_browser
def test_full_run_finds_every_branch_month_combination():
    """The regression that mattered: branch 2's slots are in month 2, and they
    were missed because the calendar stayed on the month branch 1 ended on."""
    config = {
        "url": FIXTURE,
        "transaction_type": "New Resident (First time TX registration)",
        "branches": ["Downtown", "Burnett Bayland", "Spring Branch"],
        "months_to_check": 2,
    }
    slots = checker.run_check(config, FIXTURE, screenshot_dir="/tmp")
    got = {(s["branch"], s["month_label"], s["day"]) for s in slots}
    assert got == {
        ("Downtown", "April 2026", 7),
        ("Downtown", "April 2026", 21),
        ("Downtown", "May 2026", 3),
        ("Burnett Bayland", "May 2026", 11),
        ("Burnett Bayland", "May 2026", 12),
    }
    # Spring Branch has nothing open and must contribute nothing.
    assert not [s for s in slots if s["branch"] == "Spring Branch"]
    # Results come back sorted by date.
    assert [s["iso"] for s in slots] == sorted(s["iso"] for s in slots)


@pytestmark_browser
def test_broken_page_raises_check_failed_instead_of_reporting_no_slots(tmp_path):
    """A page with no appointment button must NOT look like 'no availability'."""
    blank = tmp_path / "blank.html"
    blank.write_text("<html><body><h1>Site under maintenance</h1></body></html>")
    config = {"url": "x", "branches": ["Downtown"], "months_to_check": 1,
              "transaction_type": "New Resident"}
    with pytest.raises(checker.CheckFailed):
        checker.run_check(config, "file://" + str(blank), screenshot_dir=str(tmp_path))
