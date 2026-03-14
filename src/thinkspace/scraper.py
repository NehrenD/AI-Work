"""
Dashboard scraping and event extraction.

The student dashboard exposes upcoming events inside <div class="event_div">
elements. Each div contains free-form text that mixes the event title,
local time, and UTC time; this module parses that text into structured
Event objects.
"""

import re

import requests
from bs4 import BeautifulSoup

from .auth import BASE_URL
from .models import Event

# Default request timeout in seconds for all page fetches
_TIMEOUT = 30


def fetch_soup(session: requests.Session, url: str) -> BeautifulSoup:
    """
    Fetch *url* with the authenticated session and return a parsed soup.

    Raises requests.HTTPError on non-2xx responses.
    The timeout prevents the process from hanging on an unresponsive server.
    """
    r = session.get(url, timeout=_TIMEOUT)
    r.raise_for_status()
    return BeautifulSoup(r.text, "lxml")


# Matches date strings like "Mon 16 Mar 2026, 19:00 (Asia/Dubai)"
_DATE_RE = re.compile(
    r"((?:Mon|Tue|Wed|Thu|Fri|Sat|Sun)\s+\d{1,2}\s+\w+\s+\d{4},\s+\d{2}:\d{2}[^\n]*)"
)


def _clean_event_text(raw: str) -> tuple[str, str]:
    """
    Parse raw event-div text into (title, utc_datetime).

    The raw text looks like:
        "X dismiss  Assignment Due  Mon 16 Mar 2026, 19:00 (Asia/Dubai)
         Mon 16 Mar 2026, 15:00 (UTC)  2 days to go"

    Strategy:
      - Strip the leading "X dismiss" label added by the UI
      - Split on date-shaped tokens; the text before the first date is the title
      - Pick the date token that contains "UTC" as the canonical timestamp
    """
    # Remove the dismiss button label injected by the event widget
    raw = re.sub(r"^X\s+dismiss\s+", "", raw, flags=re.IGNORECASE).strip()

    # Split on date patterns; odd-indexed parts are the captured date strings
    parts = _DATE_RE.split(raw)
    title = parts[0].strip()

    # parts[1], parts[3], … are the captured date groups
    dates = parts[1::2]
    utc_date = next((d.strip() for d in dates if "UTC" in d), "")
    if not utc_date and dates:
        utc_date = dates[0].strip()

    return title, utc_date


def get_upcoming_events(session: requests.Session) -> list[Event]:
    """Fetch the student dashboard and return all upcoming calendar events."""
    print("[*] Fetching student dashboard...")
    soup = fetch_soup(session, f"{BASE_URL}/student/dashboard")

    events = []
    for div in soup.find_all("div", class_="event_div"):
        raw = div.get_text(" ", strip=True)
        title, date_utc = _clean_event_text(raw)
        if title:
            events.append(Event(title=title, date_utc=date_utc))

    return events
