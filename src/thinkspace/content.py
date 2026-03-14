"""
Course reader content fetching and Markdown conversion.

Each course item has a dedicated "reader" page served inside an iframe:
    /student/course/reader/<course_id>/<course_reader_id>/<course_item_id>

The reader page contains a <div class="document-assets"> with one or more
<div class="body"> sections.  Sections are separated by page-break divs and
may contain headings, paragraphs, video-label tables, and Vimeo iframes.

Conversion strategy:
  h1/h2/h3/h4          → ## / ### / #### / ##### Markdown headings
  <p> with real text   → plain paragraph lines
  video-label table    → blockquote bold label  (> **VIDEO: …**)
  Vimeo <iframe>       → blockquote link        (> [▶ title](player url))
  generic <div>        → recurse to find nested iframes
"""

import re
from pathlib import Path

import requests
from bs4 import BeautifulSoup, Tag

from .auth import BASE_URL
from .models import Course, CourseItem

# Heading tag → Markdown prefix mapping
_HEADING_LEVELS: dict[str, str] = {
    "h1": "##",
    "h2": "###",
    "h3": "####",
    "h4": "#####",
}

# Object-replacement character (U+FFFC) used as image placeholder in the VLE;
# it appears in <p> tags adjacent to video tables and should be ignored
_OBJ_REPLACEMENT = "\ufffc"


# ---------------------------------------------------------------------------
# Fetching
# ---------------------------------------------------------------------------

def fetch_item_html(
    session: requests.Session,
    course_id: str,
    item: CourseItem,
    view_referer: str = "",
) -> BeautifulSoup | None:
    """
    Fetch and parse the reader page for a single leaf course item.

    Returns None for folder items, items without a reader ID, or when the
    server redirects away (which signals session expiry).

    The Referer header is set to the course-view page that embeds the reader
    iframe — some servers validate it even though we make a direct request.
    """
    if item.is_folder or not item.course_reader_id:
        return None

    url = (
        f"{BASE_URL}/student/course/reader"
        f"/{course_id}/{item.course_reader_id}/{item.course_item_id}"
    )
    headers = {"Referer": view_referer} if view_referer else {}
    r = session.get(url, headers=headers, timeout=30)

    # A redirect away from the expected URL means the session has expired
    if r.url != url:
        return None

    return BeautifulSoup(r.text, "lxml")


# ---------------------------------------------------------------------------
# HTML → Markdown conversion helpers
# ---------------------------------------------------------------------------

def _vimeo_url(iframe_src: str) -> str:
    """
    Convert a Vimeo embed src to a player URL.

    Input:  "https://player.vimeo.com/video/350066295?app_id=122963"
    Output: "https://player.vimeo.com/video/350066295"
    """
    m = re.search(r"vimeo\.com/video/(\d+)", iframe_src)
    return f"https://player.vimeo.com/video/{m.group(1)}" if m else iframe_src


def _extract_video_label(table: Tag) -> str:
    """
    Look for a "VIDEO: …" label inside a video-placeholder table.

    The VLE renders video annotations as a table row containing a film-strip
    icon image and a <span dir="ltr">VIDEO: …</span> label cell.
    Returns the label text, or an empty string if none is found.
    """
    for span in table.find_all("span", dir="ltr"):
        text = span.get_text(strip=True)
        if text.upper().startswith("VIDEO"):
            return text
    return ""


def _process_body_div(body_div: Tag) -> list[str]:
    """
    Walk the direct children of a <div class="body"> and emit Markdown lines.

    Only direct children are iterated (not recursive find_all) so that the
    document structure maps cleanly to sequential Markdown blocks.
    Nested <div> elements that wrap iframes are handled by a single level
    of recursion.
    """
    lines: list[str] = []

    for el in body_div.children:
        if not isinstance(el, Tag):
            continue  # Skip NavigableString whitespace nodes

        tag = el.name

        # ── Headings ──────────────────────────────────────────────────────
        if tag in _HEADING_LEVELS:
            # The VLE injects <div id="menu-item-…"> anchor targets inside
            # headings; strip them so they don't pollute the heading text
            for inner in el.find_all("div"):
                inner.decompose()
            text = el.get_text(strip=True)
            if text:
                prefix = _HEADING_LEVELS[tag]
                lines.append(f"\n{prefix} {text}\n")

        # ── Paragraphs ─────────────────────────────────────────────────────
        elif tag == "p":
            text = el.get_text(strip=True)
            # Skip spacer paragraphs (empty or containing only the
            # object-replacement character used as an image placeholder)
            if text and text != _OBJ_REPLACEMENT:
                lines.append(text)

        # ── Plain hyperlinks (rare, but present in some items) ─────────────
        elif tag == "a":
            href = el.get("href", "")
            text = el.get_text(strip=True)
            if href and text:
                lines.append(f"[{text}]({href})")

        # ── Tables — video-label placeholders ─────────────────────────────
        elif tag == "table":
            # Only emit something if the table actually contains a video label;
            # layout tables (used for column margins) produce an empty string
            label = _extract_video_label(el)
            if label:
                lines.append(f"\n> **{label}**")

        # ── Divs — may wrap a Vimeo iframe ────────────────────────────────
        elif tag == "div":
            iframe = el.find("iframe")
            if iframe:
                src = iframe.get("src", "")
                title = iframe.get("title", "Video")
                if "vimeo" in src:
                    lines.append(f"> [▶ {title}]({_vimeo_url(src)})\n")
            else:
                # Generic wrapper div — recurse one level to catch any
                # content the VLE has placed inside a container element
                lines.extend(_process_body_div(el))

    return lines


def soup_to_markdown(soup: BeautifulSoup, item_title: str) -> str:
    """
    Convert a full reader-page BeautifulSoup into a Markdown string.

    The page is divided into <div class="body"> sections separated by
    page-break elements.  The first section is typically a decorative cover
    image (unit title on a coloured background) with no headings or iframes;
    it is skipped so the output starts with real content.
    """
    content = soup.find(class_="document-assets")
    if not content:
        return f"# {item_title}\n\n_No content found._\n"

    md_lines: list[str] = [f"# {item_title}\n"]

    body_divs = content.find_all("div", class_="body", recursive=False)
    for idx, body_div in enumerate(body_divs):
        # Skip the first div if it has no headings and no iframes — it is
        # almost always the decorative unit cover page
        if idx == 0:
            has_content = (
                body_div.find(re.compile(r"h[1-4]")) or
                body_div.find("iframe")
            )
            if not has_content:
                continue

        md_lines.extend(_process_body_div(body_div))

    # Normalise runs of 3+ blank lines down to a single blank line
    result = "\n".join(md_lines)
    result = re.sub(r"\n{3,}", "\n\n", result)
    return result.strip() + "\n"


# ---------------------------------------------------------------------------
# File organisation helpers
# ---------------------------------------------------------------------------

def _slugify(text: str) -> str:
    """
    Convert *text* into a filesystem-safe slug.

    Removes characters that are problematic on common OSes, then replaces
    whitespace runs with underscores.
    """
    text = re.sub(r"[^\w\s-]", "", text)
    text = re.sub(r"\s+", "_", text.strip())
    return text


def item_output_path(base_dir: Path, course: Course, unit_title: str, item_index: int, item: CourseItem) -> Path:
    """
    Return the output Path for *item* without creating any directories.

    Directory creation is the caller's responsibility so that this function
    remains a pure path computation with no side effects.

    Layout:  <base_dir>/<course_slug>/<unit_slug>/<NN>_<item_slug>.md
    """
    return (
        base_dir
        / _slugify(course.title)
        / _slugify(unit_title)
        / f"{item_index:02d}_{_slugify(item.title)}.md"
    )


# ---------------------------------------------------------------------------
# Internal scraping helpers
# ---------------------------------------------------------------------------

def _load_unit_groups(session: requests.Session, course: Course) -> list[tuple[str, list[CourseItem]]]:
    """
    Fetch the course module list and group leaf items by their parent unit.

    Returns a list of (unit_title, [leaf_items]) tuples in navigation order.
    Items that appear before any folder header are collected under an empty
    string key (unusual but handled defensively).
    """
    from .courses import get_course_modules

    all_items = get_course_modules(session, course.course_id)

    groups: list[tuple[str, list[CourseItem]]] = []
    current_folder = ""
    current_leaves: list[CourseItem] = []

    for item in all_items:
        if item.is_folder:
            # Flush accumulated leaf items before moving to the next folder
            if current_leaves:
                groups.append((current_folder, current_leaves))
                current_leaves = []
            current_folder = item.title
        else:
            current_leaves.append(item)

    # Flush the last group (no trailing folder to trigger the flush above)
    if current_leaves:
        groups.append((current_folder, current_leaves))

    return groups


def _scrape_items(
    session: requests.Session,
    course: Course,
    unit_title: str,
    unit_items: list[CourseItem],
    output_dir: Path,
) -> list[Path]:
    """
    Fetch, convert, and write Markdown for every item in *unit_items*.

    The Referer header is set to the view URL of the first item so the
    server sees a realistic request origin (as if the user clicked through
    from the course navigation sidebar).

    Returns the list of paths that were successfully written.
    """
    first = unit_items[0]
    # Build the course-view URL that would normally embed the reader iframe
    view_referer = (
        f"{BASE_URL}/student/course/view/{course.course_id}"
        f"/item/{first.course_item_id}/0/{first.course_reader_id}"
    )

    written: list[Path] = []
    for idx, item in enumerate(unit_items, start=1):
        print(f"  [{idx}/{len(unit_items)}] {item.title}")

        soup = fetch_item_html(session, course.course_id, item, view_referer)
        if soup is None:
            print(f"    [!] Could not fetch content (skipping).")
            continue

        md = soup_to_markdown(soup, item.title)

        out_path = item_output_path(output_dir, course, unit_title, idx, item)
        out_path.parent.mkdir(parents=True, exist_ok=True)  # Ensure directory exists
        out_path.write_text(md, encoding="utf-8")
        print(f"    [+] → {out_path}")
        written.append(out_path)

    return written


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def scrape_unit(
    session: requests.Session,
    course: Course,
    unit_name: str,
    output_dir: Path,
) -> list[Path]:
    """
    Scrape all content items in the unit whose title matches *unit_name*.

    Matching is case-insensitive and partial (e.g. "unit 1" matches
    "Unit 1: Getting Started").  Returns the paths of written Markdown files.
    """
    print(f"[*] Loading module list for '{course.title}'...")
    groups = _load_unit_groups(session, course)

    unit_name_lower = unit_name.lower()
    match = next(
        ((title, items) for title, items in groups if unit_name_lower in title.lower()),
        None,
    )
    if not match:
        print(f"[!] No unit found matching '{unit_name}'.")
        return []

    unit_title, unit_items = match
    print(f"[*] Scraping '{unit_title}' ({len(unit_items)} items)...")
    return _scrape_items(session, course, unit_title, unit_items, output_dir)


def scrape_course(
    session: requests.Session,
    course: Course,
    output_dir: Path,
) -> list[Path]:
    """
    Scrape every unit in *course* using the single authenticated session.

    Because the session is reused across all requests, only one login is
    ever needed regardless of how many units the course contains.
    Returns the combined list of all written Markdown file paths.
    """
    print(f"[*] Loading module list for '{course.title}'...")
    groups = _load_unit_groups(session, course)

    total_items = sum(len(items) for _, items in groups)
    print(f"[*] {len(groups)} units, {total_items} items total.\n")

    written: list[Path] = []
    for unit_title, unit_items in groups:
        print(f"── {unit_title} ({len(unit_items)} items)")
        written.extend(_scrape_items(session, course, unit_title, unit_items, output_dir))
        print()

    return written
