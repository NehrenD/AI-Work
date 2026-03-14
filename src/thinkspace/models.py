"""
Data models for the Thinkspace platform.

All models are plain dataclasses so they can be passed freely between
modules without any dependency on requests or BeautifulSoup.
"""

from dataclasses import dataclass


@dataclass
class Event:
    """A single calendar event shown on the student dashboard."""

    title: str
    date_utc: str = ""  # UTC datetime string extracted from the event widget

    def __str__(self) -> str:
        parts = [self.title]
        if self.date_utc:
            parts.append(self.date_utc)
        # Indent the date line to sit below the title when printed
        return "\n     ".join(parts)


@dataclass
class CourseItem:
    """
    One node in a course's navigation tree.

    Folders (is_folder=True) are section headings that group leaf items.
    Leaf items (is_folder=False) contain the actual readable content and
    map to a URL of the form:
        /student/course/reader/<course_id>/<course_reader_id>/<course_item_id>
    """

    title: str
    course_item_id: str   # VLE internal ID for this navigation node
    is_folder: bool        # True → section heading; False → readable content
    course_reader_id: str = ""  # Reader document ID; empty for folders


@dataclass
class Course:
    """A course card as it appears on the enrolled-courses page."""

    title: str
    course_id: str        # VLE numeric ID used in all course URLs
    description: str = "" # Short blurb from the course card
