"""
Authentication helpers for campus.thinkspace.ac.uk.

The site uses a standard Laravel CSRF-token flow:
  1. GET /login  →  extract the hidden _token field from the form
  2. POST /login with {_token, email, password}
  3. A 3xx redirect *away* from /login indicates success
"""

import re

import requests
from bs4 import BeautifulSoup

# Base URL shared across all modules so there is a single source of truth
BASE_URL = "https://campus.thinkspace.ac.uk"
LOGIN_URL = f"{BASE_URL}/login"

# Mimic a real desktop browser to avoid bot-detection rejections
_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36"
)


def create_session() -> requests.Session:
    """Return a new requests.Session pre-configured with browser-like headers."""
    session = requests.Session()
    session.headers.update({
        "User-Agent": _USER_AGENT,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
    })
    return session


def login(session: requests.Session, email: str, password: str) -> None:
    """
    Authenticate the session against the Thinkspace login form.

    Raises RuntimeError on failure so the caller can decide how to handle it
    (e.g. print a message and sys.exit vs. retry).
    """
    print("[*] Fetching login page...")
    r = session.get(LOGIN_URL)
    r.raise_for_status()

    # The CSRF token is embedded in a hidden <input name="_token"> field
    soup = BeautifulSoup(r.text, "lxml")
    token_el = soup.find("input", {"name": "_token"})
    if not token_el:
        raise RuntimeError("CSRF token not found on login page")
    csrf = token_el["value"]

    # Referer and Origin are required by Laravel's CSRF middleware
    session.headers.update({"Referer": LOGIN_URL, "Origin": BASE_URL})

    print("[*] Submitting credentials...")
    r2 = session.post(
        LOGIN_URL,
        data={"_token": csrf, "email": email, "password": password},
        allow_redirects=False,  # We check the redirect destination manually
    )
    r2.raise_for_status()

    # A successful login redirects away from /login; failure redirects back to it
    location = r2.headers.get("Location", "")
    if r2.status_code not in (301, 302, 303) or "/login" in location:
        # Follow the redirect to read the server's error message
        r3 = session.get(LOGIN_URL)
        soup3 = BeautifulSoup(r3.text, "lxml")
        err_el = soup3.find("ul", class_=re.compile("text-red"))
        msg = err_el.get_text(strip=True) if err_el else "Unknown error"
        raise RuntimeError(f"Login failed: {msg}")

    print("[+] Login successful!")
