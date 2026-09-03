"""Split Wilma homework into upcoming vs past using the weekly timetable."""
from __future__ import annotations

from datetime import datetime, timedelta
import re
from zoneinfo import ZoneInfo

from .api import parse_date, parse_time
from .const import TIMEZONE
from .models import Homework, Lesson

_TZ = ZoneInfo(TIMEZONE)
_SUBJECT_SPLIT = re.compile(r"[\s:/\-–|,]+")


def _norm_subject(value: str) -> str:
    return re.sub(r"[^a-z0-9åäöéèü]+", "", (value or "").casefold())


def subjects_match(left: str, right: str) -> bool:
    """Loose subject compare: exact, containment, or a shared token/code."""
    a, b = _norm_subject(left), _norm_subject(right)
    if not a or not b:
        return False
    if a == b or a in b or b in a:
        return True
    tokens_a = {_norm_subject(part) for part in _SUBJECT_SPLIT.split(left or "") if part}
    tokens_b = {_norm_subject(part) for part in _SUBJECT_SPLIT.split(right or "") if part}
    tokens_a.discard("")
    tokens_b.discard("")
    return bool(tokens_a and tokens_b and tokens_a & tokens_b)


def _weekly_lessons(schedule: list[Lesson], subject: str) -> list[Lesson]:
    return [lesson for lesson in schedule if lesson.day and subjects_match(subject, lesson.subject)]


def _next_weekly_end(lessons: list[Lesson], start_day, tz) -> datetime | None:
    """End of the first weekly slot on or after start_day."""
    for offset in range(0, 14):
        day = start_day + timedelta(days=offset)
        weekday = day.isoweekday()
        ends: list[datetime] = []
        for lesson in lessons:
            if lesson.day != weekday:
                continue
            end_t = parse_time(lesson.end) or parse_time(lesson.start)
            if not end_t:
                continue
            ends.append(datetime.combine(day, end_t, tzinfo=tz))
        if ends:
            return min(ends)
    return None


def split_homework(
    homework: list[Homework],
    schedule: list[Lesson],
    now: datetime | None = None,
) -> tuple[list[Homework], list[Homework]]:
    """Return (upcoming, past).

    A homework item moves to past once that subject's next weekly lesson
    (day + start/end) has ended. No timetable match keeps it upcoming.
    """
    now = now or datetime.now(_TZ)
    if now.tzinfo is None:
        now = now.replace(tzinfo=_TZ)
    upcoming: list[Homework] = []
    past: list[Homework] = []
    for item in homework:
        lessons = _weekly_lessons(schedule, item.subject)
        if not lessons:
            upcoming.append(item)
            continue
        start_day = parse_date(item.date) or now.date()
        due_end = _next_weekly_end(lessons, start_day, now.tzinfo)
        if due_end is None:
            upcoming.append(item)
        elif now >= due_end:
            past.append(item)
        else:
            upcoming.append(item)
    upcoming.sort(key=lambda item: parse_date(item.date) or datetime.max.date())
    past.sort(key=lambda item: parse_date(item.date) or datetime.min.date(), reverse=True)
    return upcoming, past
