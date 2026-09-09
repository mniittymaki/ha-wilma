"""Split Wilma homework into upcoming vs past using the weekly timetable."""
from __future__ import annotations

from datetime import datetime, timedelta
import re
from zoneinfo import ZoneInfo

from .api import parse_date, parse_time
from .const import TIMEZONE
from .models import Course, Homework, Lesson

_TZ = ZoneInfo(TIMEZONE)
_SUBJECT_SPLIT = re.compile(r"[\s:/\-–|,]+")
_WEEKDAY = {1: "ma", 2: "ti", 3: "ke", 4: "to", 5: "pe", 6: "la", 7: "su"}

# Official-ish codes → long names. Prefixes like ENA1 collapse to ENA.
_CODE_NAMES: dict[str, tuple[str, ...]] = {
    "suk": ("suomen kieli ja kirjallisuus", "suomen kieli", "kirjallisuus", "aidinkieli", "äidinkieli"),
    "ena": ("englanti",),
    "enb": ("englanti",),
    "en": ("englanti",),
    "rub": ("ruotsi",),
    "rua": ("ruotsi",),
    "ru": ("ruotsi",),
    "ma": ("matematiikka",),
    "hi": ("historia",),
    "ku": ("kuvataide",),
    "ko": ("kotitalous",),
    "ks": ("kasityo", "käsityö"),
    "fy": ("fysiikka",),
    "te": ("terveystieto",),
    "op": ("oppilaanohjaus", "opo"),
    "li": ("liikunta",),
    "ue": ("uskonto",),
    "ueel": ("uskonto", "et", "elamankatsomustieto", "elämänkatsomustieto"),
    "mt": ("musiikki",),
    "mu": ("musiikki",),
    "ke": ("kemia",),
    "bi": ("biologia",),
    "ge": ("maantieto",),
    "yh": ("yhteiskuntaoppi",),
}


def _norm(value: str) -> str:
    return re.sub(r"[^a-z0-9åäöéèü]+", "", (value or "").casefold())


def slot_code(subject: str) -> str:
    """ENA1_Wera V357 → ENA1; 8.FY_EetuM → FY; 7DEF.LI_… → LI."""
    raw = (subject or "").strip()
    if not raw:
        return ""
    token = raw.split("_", 1)[0].split()[0]
    if "." in token:
        token = token.split(".")[-1]
    return token


def _letter_prefix(code: str) -> str:
    match = re.match(r"^[a-zåäö]+", _norm(code))
    return match.group(0) if match else _norm(code)


def _tokens(value: str) -> set[str]:
    out = set()
    for part in _SUBJECT_SPLIT.split(value or ""):
        n = _norm(part)
        if len(n) >= 2:
            out.add(n)
    code = slot_code(value)
    if code:
        out.add(_norm(code))
        prefix = _letter_prefix(code)
        if prefix:
            out.add(prefix)
    return out


_NAME_CODES: dict[str, set[str]] = {}
for _code, _names in _CODE_NAMES.items():
    for _name in _names:
        _NAME_CODES.setdefault(_norm(_name), set()).add(_code)


def _expand(label: str, aliases: dict[str, set[str]]) -> set[str]:
    keys = {_norm(label), *(_tokens(label))}
    code = _norm(slot_code(label))
    prefix = _letter_prefix(slot_code(label) or label)
    extra: set[str] = set()
    for key in list(keys) + [code, prefix]:
        extra |= aliases.get(key, set())
        extra |= {_norm(name) for name in _CODE_NAMES.get(key, ())}
        extra |= set(_NAME_CODES.get(key, set()))
    keys |= extra
    keys.discard("")
    return keys


def _course_aliases(courses: list[Course] | None) -> dict[str, set[str]]:
    aliases: dict[str, set[str]] = {}

    def _add(key: str, *values: str) -> None:
        nk = _norm(key)
        if not nk:
            return
        bucket = aliases.setdefault(nk, set())
        for value in values:
            n = _norm(value)
            if n:
                bucket.add(n)
            code = _norm(slot_code(value))
            if code:
                bucket.add(code)
                bucket.add(_letter_prefix(value))

    for course in courses or []:
        _add(course.code, course.code, course.name)
        _add(course.name, course.code, course.name)
        _add(slot_code(course.code or course.name), course.code, course.name)
    return aliases



def _language_track(label: str) -> tuple[str, str] | None:
    """('en','a'|'b'|'') for English, ('ru', …) for Swedish."""
    compact = _norm(label)
    raw = (label or "").casefold()
    family = ""
    if compact.startswith("en") or "englanti" in compact:
        family = "en"
    elif compact.startswith("ru") or "ruotsi" in compact:
        family = "ru"
    else:
        return None
    if family == "en" and compact.startswith("enb"):
        return family, "b"
    if family == "en" and compact.startswith("ena"):
        return family, "a"
    if family == "ru" and compact.startswith("rub"):
        return family, "b"
    if family == "ru" and compact.startswith("rua"):
        return family, "a"
    if re.search(r"(?:^|[^a-zåäö])b[\s\-]*\d", raw) or "b-kieli" in raw or "b kieli" in raw:
        return family, "b"
    if re.search(r"(?:^|[^a-zåäö])a[\s\-]*\d", raw) or "a-kieli" in raw or "a kieli" in raw:
        return family, "a"
    return family, ""


def subjects_match(left: str, right: str, aliases: dict[str, set[str]] | None = None) -> bool:
    """Match long homework names to timetable codes (Englanti, A1 ↔ ENA1_Wera)."""
    aliases = aliases or {}
    a, b = _expand(left, aliases), _expand(right, aliases)
    if not a or not b:
        return False
    if a & b:
        track_l, track_r = _language_track(left), _language_track(right)
        if track_l and track_r and track_l[0] == track_r[0]:
            if track_l[1] and track_r[1] and track_l[1] != track_r[1]:
                return False
        return True
    return False


def _lesson_day(lesson: Lesson) -> int:
    if lesson.day:
        return lesson.day
    parsed = parse_date(lesson.date)
    return parsed.isoweekday() if parsed else 0


def _weekly_lessons(schedule: list[Lesson], subject: str, aliases: dict[str, set[str]]) -> list[Lesson]:
    return [lesson for lesson in schedule if _lesson_day(lesson) and subjects_match(subject, lesson.subject, aliases)]


def _next_weekly_end(lessons: list[Lesson], start_day, tz) -> tuple[datetime, Lesson] | None:
    """End of the first weekly slot strictly after start_day."""
    for offset in range(1, 15):
        day = start_day + timedelta(days=offset)
        weekday = day.isoweekday()
        found: list[tuple[datetime, Lesson]] = []
        for lesson in lessons:
            if _lesson_day(lesson) != weekday:
                continue
            end_t = parse_time(lesson.end) or parse_time(lesson.start)
            if not end_t:
                continue
            found.append((datetime.combine(day, end_t, tzinfo=tz), lesson))
        if found:
            return min(found, key=lambda item: item[0])
    return None


def _hint_next(due: datetime, lesson: Lesson) -> str:
    code = slot_code(lesson.subject) or lesson.subject
    weekday = _WEEKDAY.get(due.isoweekday(), "")
    clock = due.strftime("%H:%M")
    return f"lukujärjestys {code} {weekday} {due.day}.{due.month}. {clock}".strip()


def split_homework(
    homework: list[Homework],
    schedule: list[Lesson],
    now: datetime | None = None,
    courses: list[Course] | None = None,
) -> tuple[list[Homework], list[Homework]]:
    """Return (upcoming, past).

    A homework item moves to past once the next weekly lesson AFTER the
    homework date has ended (same-day lesson is the assignment, not the due).
    """
    now = now or datetime.now(_TZ)
    if now.tzinfo is None:
        now = now.replace(tzinfo=_TZ)
    aliases = _course_aliases(courses)
    upcoming: list[Homework] = []
    past: list[Homework] = []
    for item in homework:
        lessons = _weekly_lessons(schedule, item.subject, aliases)
        if not lessons:
            codes = sorted({slot_code(lesson.subject) for lesson in schedule if slot_code(lesson.subject)})
            extra = f" ({', '.join(codes[:8])})" if codes else ""
            item.hint = f"ei lukujärjestysosumaa{extra}"
            upcoming.append(item)
            continue
        start_day = parse_date(item.date) or now.date()
        nxt = _next_weekly_end(lessons, start_day, now.tzinfo)
        if nxt is None:
            item.hint = f"lukujärjestys {slot_code(lessons[0].subject) or lessons[0].subject}, ei kellonaikaa"
            upcoming.append(item)
            continue
        due_end, lesson = nxt
        if now >= due_end:
            item.hint = f"tunti ohi · {_hint_next(due_end, lesson)}"
            past.append(item)
        else:
            item.hint = _hint_next(due_end, lesson)
            upcoming.append(item)
    upcoming.sort(key=lambda item: parse_date(item.date) or datetime.max.date())
    past.sort(key=lambda item: parse_date(item.date) or datetime.min.date(), reverse=True)
    return upcoming, past
