"""
Command-line interface for the Thinkspace scraper.

Subcommands
-----------
events          Show upcoming calendar events from the student dashboard.
modules         List the module/unit tree for a course.
scrape          Scrape a single unit and save each item as a Markdown file.
scrape-course   Scrape every unit in a course.

Session handling
----------------
All commands call _authenticated_session() which tries to reuse cookies
saved from the previous run before falling back to a full login.  This
means only the very first invocation (or one after a session expiry) will
actually hit the login endpoint.
"""

import argparse
import os
import sys
import warnings
from pathlib import Path

import requests
from dotenv import load_dotenv

from .auth import create_session, login
from .courses import find_course, get_course_modules
from .scraper import get_upcoming_events
from .session_store import is_session_valid, load_session, save_session

# Suppress urllib3 SSL warnings that fire when verify=False is used upstream
warnings.filterwarnings("ignore")


# ---------------------------------------------------------------------------
# Credential and session helpers
# ---------------------------------------------------------------------------

def _load_credentials() -> tuple[str, str]:
    """
    Read credentials from environment / .env file.

    Exits with a helpful message if either variable is missing so the user
    knows exactly what to set up.
    """
    load_dotenv()
    email = os.environ.get("THINKSPACE_EMAIL", "")
    password = os.environ.get("THINKSPACE_PASSWORD", "")
    if not email or not password:
        print("[!] Set THINKSPACE_EMAIL and THINKSPACE_PASSWORD in your .env file.")
        sys.exit(1)
    return email, password


def _authenticated_session() -> requests.Session:
    """
    Return a fully authenticated requests.Session.

    Tries saved cookies first; only performs a network login when the saved
    session is missing or has expired.  Saves fresh cookies after login so
    subsequent calls can skip the login step.
    """
    session = create_session()

    if load_session(session):
        if is_session_valid(session):
            print("[*] Resuming existing session (no login needed).")
            return session
        print("[*] Saved session expired, logging in again...")
    else:
        print("[*] No saved session found, logging in...")

    email, password = _load_credentials()
    try:
        login(session, email, password)
    except Exception as e:
        print(f"[!] {e}")
        sys.exit(1)

    save_session(session)
    return session


def _resolve_course(session: requests.Session, name: str):
    """
    Look up a course by partial name and return it, or exit on failure.

    Centralises the repeated find-course-or-exit pattern used by the
    modules, scrape, and scrape-course commands.
    """
    print(f"[*] Searching for course matching '{name}'...")
    course = find_course(session, name)
    if not course:
        print(f"[!] No course found matching '{name}'.")
        sys.exit(1)
    return course


# ---------------------------------------------------------------------------
# Subcommand handlers
# ---------------------------------------------------------------------------

def cmd_events(_args) -> None:
    """Fetch and pretty-print upcoming calendar events."""
    session = _authenticated_session()
    events = get_upcoming_events(session)

    if not events:
        print("[!] No upcoming events found on the dashboard.")
        return

    print(f"\n{'='*60}")
    print(f"  UPCOMING EVENTS  ({len(events)} total)")
    print(f"{'='*60}")
    for i, ev in enumerate(events, 1):
        print(f"\n  {i}. {ev}")
    print(f"\n{'='*60}\n")


def cmd_modules(args) -> None:
    """Print the full unit/item tree for the matched course."""
    session = _authenticated_session()
    course = _resolve_course(session, args.course)

    print(f"[*] Fetching modules for: {course.title} (id={course.course_id})")
    items = get_course_modules(session, course.course_id)

    if not items:
        print("[!] No modules found.")
        return

    print(f"\n{'='*60}")
    print(f"  {course.title.upper()}")
    print(f"{'='*60}")
    for item in items:
        if item.is_folder:
            print(f"\n  [ {item.title} ]")
        else:
            print(f"      - {item.title}")
    print(f"\n{'='*60}\n")


def cmd_scrape(args) -> None:
    """Scrape a single unit and write one Markdown file per item."""
    from .content import scrape_unit

    session = _authenticated_session()
    course = _resolve_course(session, args.course)

    written = scrape_unit(session, course, args.unit, Path(args.output))
    if written:
        print(f"\n[+] Done. {len(written)} file(s) written to {args.output}/")
    else:
        print("[!] Nothing was written.")


def cmd_scrape_course(args) -> None:
    """Scrape every unit in a course and write one Markdown file per item."""
    from .content import scrape_course

    session = _authenticated_session()
    course = _resolve_course(session, args.course)

    written = scrape_course(session, course, Path(args.output))
    if written:
        print(f"[+] Done. {len(written)} file(s) written to {args.output}/")
    else:
        print("[!] Nothing was written.")


# ---------------------------------------------------------------------------
# Argument parser and entry point
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        prog="thinkspace",
        description="Thinkspace Education Platform CLI",
    )
    sub = parser.add_subparsers(dest="command")

    # ── events ────────────────────────────────────────────────────────────
    sub.add_parser("events", help="Show upcoming events (default when no command given)")

    # ── modules ───────────────────────────────────────────────────────────
    modules_p = sub.add_parser("modules", help="List the module tree for a course")
    modules_p.add_argument("course", help="Partial course name (case-insensitive)")

    # ── scrape ────────────────────────────────────────────────────────────
    scrape_p = sub.add_parser("scrape", help="Scrape one unit → Markdown files")
    scrape_p.add_argument("course", help="Partial course name")
    scrape_p.add_argument("unit",   help="Partial unit name (e.g. 'Unit 1')")
    scrape_p.add_argument("--output", "-o", default="content",
                          help="Output base directory (default: ./content)")

    # ── scrape-course ─────────────────────────────────────────────────────
    scrape_course_p = sub.add_parser("scrape-course", help="Scrape all units → Markdown files")
    scrape_course_p.add_argument("course", help="Partial course name")
    scrape_course_p.add_argument("--output", "-o", default="content",
                                 help="Output base directory (default: ./content)")

    args = parser.parse_args()

    # Dispatch to the appropriate handler; default to events if no command given
    if args.command == "modules":
        cmd_modules(args)
    elif args.command == "scrape":
        cmd_scrape(args)
    elif args.command == "scrape-course":
        cmd_scrape_course(args)
    else:
        cmd_events(args)


if __name__ == "__main__":
    main()
