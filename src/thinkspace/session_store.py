"""
Persistent session cookie storage.

After a successful login the session cookies are written to a JSON file
under ~/.config/thinkspace/. On the next run the cookies are reloaded and
probed with a /ping request — if the server confirms the session is still
alive we skip the login step entirely, reducing unnecessary auth traffic.
"""

import json
from pathlib import Path

import requests

from .auth import BASE_URL

# Store cookies in the standard XDG-like config location
_SESSION_FILE = Path.home() / ".config" / "thinkspace" / "session.json"


def save_session(session: requests.Session) -> None:
    """Persist all current session cookies to disk as JSON."""
    _SESSION_FILE.parent.mkdir(parents=True, exist_ok=True)
    cookies = dict(session.cookies)
    _SESSION_FILE.write_text(json.dumps(cookies, indent=2))


def load_session(session: requests.Session) -> bool:
    """
    Restore cookies from disk into *session*.

    Returns True if a cookie file existed (even if the session turns out to
    be expired), False if no file was found.
    """
    if not _SESSION_FILE.exists():
        return False
    try:
        cookies = json.loads(_SESSION_FILE.read_text())
        for k, v in cookies.items():
            session.cookies.set(k, v)
        return True
    except Exception:
        # Corrupt or unreadable file — treat as missing
        return False


def is_session_valid(session: requests.Session) -> bool:
    """
    Probe the /ping endpoint to confirm the session is still authenticated.

    The endpoint returns the string "0" (or redirects to login) when the
    session has expired; any other 200 response means we are still logged in.
    """
    try:
        r = session.get(f"{BASE_URL}/ping", timeout=10)
        return r.status_code == 200 and r.text.strip() != "0"
    except Exception:
        return False


def clear_session() -> None:
    """Delete the saved cookie file, forcing a fresh login next run."""
    if _SESSION_FILE.exists():
        _SESSION_FILE.unlink()
