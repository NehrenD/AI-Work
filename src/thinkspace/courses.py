"""
Course listing and module tree extraction.

Two distinct pages are involved:
  - /student/course          → the enrolled-courses grid; one card per course
  - /student/course/view/<id> → a single course; left sidebar contains the
                                module tree inside <ul id="courseTree">

HTML conventions used by the VLE:
  Course card  → <button class="course_box" id="course-<id>">
  Tree folder  → <li blocklevel="1" isfolder="1">
  Tree leaf    → <li blocklevel="2" isfolder="0">
"""

import re

import requests

from .auth import BASE_URL
from .models import Course, CourseItem
from .scraper import fetch_soup

COURSES_URL = f"{BASE_URL}/student/course"


def get_all_courses(session: requests.Session) -> list[Course]:
    """
    Scrape the enrolled-courses page and return every course card.

    Each card is a <button class="course_box"> whose id attribute encodes
    the course ID (e.g. id="course-237").  The title is in an <h2> that also
    contains a hidden "Hide" button and an ID span, both of which are stripped
    before reading the text.
    """
    soup = fetch_soup(session, COURSES_URL)

    courses = []
    for btn in soup.find_all("button", class_="course_box"):
        # Extract the numeric course ID from the element's id attribute
        course_id_match = re.search(r"course-(\d+)", btn.get("id", ""))
        if not course_id_match:
            continue
        course_id = course_id_match.group(1)

        h2 = btn.find("h2", class_="searchTableCell")
        if not h2:
            continue

        # The h2 contains a <span> with the hidden course ID and a "Hide"
        # <button> — remove both so get_text() returns only the course title
        for child in h2.find_all(["span", "button"]):
            child.decompose()
        title = h2.get_text(strip=True)

        desc_el = btn.find(class_="body_text")
        description = desc_el.get_text(strip=True) if desc_el else ""

        courses.append(Course(title=title, course_id=course_id, description=description))

    return courses


def find_course(session: requests.Session, name: str) -> Course | None:
    """
    Return the first course whose title contains *name* (case-insensitive).

    Returns None if no match is found.
    """
    name_lower = name.lower()
    for course in get_all_courses(session):
        if name_lower in course.title.lower():
            return course
    return None


def get_course_modules(session: requests.Session, course_id: str) -> list[CourseItem]:
    """
    Parse the left-sidebar course tree for *course_id* and return all nodes.

    The tree is rendered as a flat <ul id="courseTree"> where depth is
    encoded via the blocklevel attribute rather than actual nesting:
      blocklevel="1"  isfolder="1"  → section heading (unit)
      blocklevel="2"  isfolder="0"  → leaf content item

    Each leaf item carries two IDs:
      courseitemid   — identifies the navigation node
      coursereaderid — identifies the reader document; used in the reader URL
    """
    soup = fetch_soup(session, f"{BASE_URL}/student/course/view/{course_id}")

    tree = soup.find(id="courseTree")
    if not tree:
        return []

    items = []
    for li in tree.find_all("li", attrs={"blocklevel": True}):
        title_div = li.find(class_="courseTreeLink")
        if not title_div:
            continue

        # Font-Awesome <i> tags render as icons in the browser but produce
        # garbage text in get_text(); remove them before reading the title
        for icon in title_div.find_all("i"):
            icon.decompose()

        title = title_div.get_text(strip=True)
        if not title:
            continue

        items.append(CourseItem(
            title=title,
            course_item_id=li.get("courseitemid", ""),
            is_folder=li.get("isfolder") == "1",
            course_reader_id=title_div.get("coursereaderid", ""),
        ))

    return items
