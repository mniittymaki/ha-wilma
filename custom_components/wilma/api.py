"""Fetch and parse Wilma school pages with an authenticated session."""
from __future__ import annotations

from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo
import json
import logging
import re
from typing import Any

import aiohttp

from .const import PROBE_PATHS, TIMEZONE
from .models import Child, Course, Exam, Homework, Lesson, LessonNote, NewsItem, SchoolData

_LOGGER = logging.getLogger(__name__)

DATE_RE = re.compile(r"(\d{4}-\d{2}-\d{2}|\d{1,2}\.\d{1,2}\.\d{4})")

DATE_KEYS = ("Date", "date", "Day", "day", "DateTime", "Pvm")
TIME_KEYS = ("Time", "time", "Start", "start", "StartTime", "Hour")
KIND_KEYS = (
    "TypeName",
    "typeName",
    "CodeName",
    "ObservationType",
    "TypeCaption",
    "Caption",
    "caption",
    "Type",
    "type",
    "Name",
    "name",
    "Code",
    "code",
)
TEXT_KEYS = ("Text", "text", "Explanation", "explanation", "Note", "note", "Comment", "comment", "Content", "Remark")
SUBJECT_KEYS = (
    "CourseName",
    "courseName",
    "fullCaption",
    "shortCaption",
    "Subject",
    "subject",
    "Course",
    "course",
    "GroupName",
    "Group",
)
TEACHER_KEYS = ("TeacherName", "teacherName", "Teacher", "teacher")
CODE_KEYS = ("CodeId", "codeId", "Code", "code", "TypeId", "Id")


def parse_date(value: str | None) -> date | None:
    if not value:
        return None
    text = str(value).strip()
    for fmt in ("%Y-%m-%d", "%d.%m.%Y", "%Y-%m-%dT%H:%M:%S", "%d.%m.%Y %H:%M"):
        try:
            return datetime.strptime(text[:19], fmt).date()
        except ValueError:
            continue
    match = DATE_RE.search(text)
    if not match:
        return None
    return parse_date(match.group(1))


def parse_time(value: str | None) -> time | None:
    if not value:
        return None
    text = str(value).strip()
    for fmt in ("%H:%M", "%H.%M", "%H:%M:%S"):
        try:
            return datetime.strptime(text[:8], fmt).time()
        except ValueError:
            continue
    return None


def _abs(base: str, uid: str, path: str) -> str:
    uid = uid.strip("/")
    path = path.strip("/")
    if path.startswith("!"):
        return f"{base.rstrip('/')}/{path}"
    return f"{base.rstrip('/')}/{uid}/{path}"


def _as_text(val: Any) -> str:
    if val is None or val == "":
        return ""
    if isinstance(val, dict):
        return str(
            val.get("Name")
            or val.get("name")
            or val.get("Caption")
            or val.get("caption")
            or val.get("Code")
            or ""
        )
    if isinstance(val, list) and val:
        return _as_text(val[0])
    return str(val).strip()


def _pick(item: dict, keys: tuple[str, ...]) -> str:
    for key in keys:
        if key in item and item[key] not in (None, ""):
            text = _as_text(item[key])
            if text:
                return text
    return ""


def _first_date(item: dict) -> str:
    text = _pick(item, DATE_KEYS)
    if text:
        parsed = parse_date(text)
        return parsed.isoformat() if parsed else text
    for val in item.values():
        if isinstance(val, str) and DATE_RE.search(val):
            parsed = parse_date(val)
            return parsed.isoformat() if parsed else DATE_RE.search(val).group(1)
    return ""


def _note_from_dict(item: dict) -> LessonNote | None:
    date_s = _first_date(item)
    kind = _pick(item, KIND_KEYS)
    text = _pick(item, TEXT_KEYS)
    subject = _pick(item, SUBJECT_KEYS)
    code = _pick(item, CODE_KEYS)
    if not date_s:
        return None
    # Skip timetable slots that only carry a date.
    if not (kind or text or code or subject):
        return None
    if not kind and not text and subject and not any(k in item for k in ("Type", "Code", "Note", "Text", "CodeId")):
        return None
    return LessonNote(
        date=date_s,
        time=_pick(item, TIME_KEYS),
        subject=subject,
        teacher=_pick(item, TEACHER_KEYS),
        kind=kind or code,
        text=text,
        code=code,
    )


def _walk_notes(obj: Any, acc: list[LessonNote], depth: int = 0) -> None:
    if depth > 8:
        return
    if isinstance(obj, dict):
        note = _note_from_dict(obj)
        if note:
            acc.append(note)
        for key, val in obj.items():
            low = str(key).lower()
            if low in {"schedule", "reservations", "events", "calendar", "lessons"}:
                continue
            _walk_notes(val, acc, depth + 1)
    elif isinstance(obj, list):
        for item in obj:
            _walk_notes(item, acc, depth + 1)


def _group_info(obj: dict) -> tuple[str, str, str]:
    groups = obj.get("Groups") or obj.get("groups") or []
    if isinstance(groups, dict):
        groups = [groups]
    first = groups[0] if isinstance(groups, list) and groups and isinstance(groups[0], dict) else obj
    subject = (
        _pick(first, SUBJECT_KEYS)
        or _as_text(first.get("ShortCaption") or first.get("shortCaption"))
        or _pick(obj, SUBJECT_KEYS)
    )
    teacher = _pick(first, TEACHER_KEYS) or _pick(obj, TEACHER_KEYS)
    teachers = first.get("Teachers") or first.get("teachers") or obj.get("Teachers")
    if not teacher and isinstance(teachers, list) and teachers:
        teacher = _as_text(teachers[0])
    room = _as_text(first.get("Room") or first.get("room") or obj.get("Room") or obj.get("room"))
    rooms = first.get("Rooms") or first.get("rooms") or obj.get("Rooms")
    if not room and isinstance(rooms, list) and rooms:
        room = _as_text(rooms[0])
    return subject, teacher, room


def _walk_lessons(obj: Any, acc: list[Lesson], depth: int = 0) -> None:
    if depth > 7:
        return
    if isinstance(obj, dict):
        start = _pick(obj, ("Start", "start", "StartTime", "startTime", "Begin", "begin"))
        end = _pick(obj, ("End", "end", "EndTime", "endTime"))
        day_present = any(key in obj for key in ("Day", "day", "WeekDay", "weekday"))
        if start and (end or day_present or obj.get("Groups") or obj.get("groups")):
            subject, teacher, room = _group_info(obj)
            dates = obj.get("dateArray") or obj.get("Dates") or obj.get("dates") or obj.get("DateArray") or []
            if not isinstance(dates, list):
                dates = []
            try:
                day = int(obj.get("Day") or obj.get("day") or obj.get("WeekDay") or 0)
            except (TypeError, ValueError):
                day = 0
            acc.append(
                Lesson(
                    day=day,
                    date=_first_date(obj),
                    start=start,
                    end=end,
                    subject=subject,
                    teacher=teacher,
                    room=room,
                    dates=[str(item) for item in dates],
                )
            )
        for key, val in obj.items():
            if str(key).lower() in {"teachers", "rooms"}:
                continue
            _walk_lessons(val, acc, depth + 1)
    elif isinstance(obj, list):
        for item in obj:
            _walk_lessons(item, acc, depth + 1)


def _exam_from_dict(item: dict) -> Exam | None:
    date_s = _first_date(item)
    name = _pick(item, ("Name", "name", "Title", "title", "Caption", "caption"))
    subject = _pick(item, SUBJECT_KEYS) or _as_text(item.get("ShortCaption") or item.get("shortCaption"))
    topic = _pick(item, ("Topic", "topic", "Description", "description", "Summary", "summary"))
    grade = _pick(item, ("Grade", "grade", "Mark", "mark"))
    seen = item.get("ExamSeen") not in (None, "")
    teacher = _pick(item, TEACHER_KEYS)
    if not date_s:
        return None
    if not (name or subject or topic or grade):
        return None
    if "Start" in item and "End" in item and not (name or topic or grade):
        return None
    return Exam(
        subject=subject,
        date=date_s,
        name=name,
        grade=grade,
        seen=seen,
        teacher=teacher,
        topic=topic,
    )


def _walk_exams(obj: Any, exams: list[Exam], grades: list[Exam], depth: int = 0) -> None:
    if depth > 6:
        return
    if isinstance(obj, dict):
        exam = _exam_from_dict(obj)
        if exam:
            (grades if exam.grade else exams).append(exam)
        for key, val in obj.items():
            low = str(key).lower()
            if low in {"schedule", "reservations", "rooms", "teachers"}:
                continue
            _walk_exams(val, exams, grades, depth + 1)
    elif isinstance(obj, list):
        for item in obj:
            _walk_exams(item, exams, grades, depth + 1)


HW_TEXT_KEYS = (
    "Homework",
    "homework",
    "Assignment",
    "assignment",
    "Task",
    "task",
    "HomeworkText",
    "Content",
)


def _hw_from_dict(item: dict, subject: str = "") -> Homework | None:
    # A list of homework items must be walked, not collapsed to the first entry.
    if any(isinstance(item.get(key), list) for key in HW_TEXT_KEYS):
        return None
    text = _pick(item, HW_TEXT_KEYS)
    if not text:
        return None
    if DATE_RE.fullmatch(text.strip()) or text in ("[]", "()"):
        return None
    subj = _pick(item, SUBJECT_KEYS) or subject
    return Homework(
        subject=subj,
        text=text,
        date=_first_date(item),
        teacher=_pick(item, TEACHER_KEYS),
    )


def _homework_from_text(text: str, subject: str = "") -> Homework | None:
    cleaned = text.strip()
    if not cleaned or DATE_RE.fullmatch(cleaned) or cleaned in ("[]", "()"):
        return None
    return Homework(subject=subject, text=cleaned)


_HW_TEXT_KEY_SET = {key.lower() for key in HW_TEXT_KEYS}


def _walk_homework(obj: Any, acc: list[Homework], depth: int = 0, subject: str = "") -> None:
    if depth > 6:
        return
    if isinstance(obj, dict):
        current = _pick(obj, SUBJECT_KEYS) or _as_text(obj.get("ShortCaption") or obj.get("shortCaption")) or subject
        hw = _hw_from_dict(obj, current)
        if hw:
            acc.append(hw)
        for key, val in obj.items():
            low = str(key).lower()
            if low in {"reservations", "rooms", "teachers"}:
                continue
            # Expand a Homework-like list in place; do not treat other strings as tasks.
            if low in _HW_TEXT_KEY_SET and isinstance(val, list):
                for item in val:
                    if isinstance(item, str):
                        parsed = _homework_from_text(item, current)
                        if parsed:
                            acc.append(parsed)
                    else:
                        _walk_homework(item, acc, depth + 1, current)
                continue
            _walk_homework(val, acc, depth + 1, current)
    elif isinstance(obj, list):
        for item in obj:
            _walk_homework(item, acc, depth + 1, subject)


def _dedupe_homework(items: list[Homework]) -> list[Homework]:
    seen: set[tuple[str, str, str]] = set()
    out: list[Homework] = []
    for item in items:
        key = (item.date, item.subject, item.text)
        if key in seen:
            continue
        seen.add(key)
        out.append(item)
    return out



def _dedupe_notes(notes: list[LessonNote]) -> list[LessonNote]:
    seen: set[tuple[str, str, str, str]] = set()
    out: list[LessonNote] = []
    for note in notes:
        key = (note.date, note.kind, note.subject, note.text)
        if key in seen:
            continue
        seen.add(key)
        out.append(note)
    out.sort(key=lambda item: item.date, reverse=True)
    return out


def _dedupe_lessons(lessons: list[Lesson]) -> list[Lesson]:
    seen: set[tuple[int, str, str, str]] = set()
    out: list[Lesson] = []
    for lesson in lessons:
        key = (lesson.day, lesson.start, lesson.end, lesson.subject)
        if key in seen:
            continue
        seen.add(key)
        out.append(lesson)
    out.sort(key=lambda item: (item.day, item.start or ""))
    return out


async def _get(session: aiohttp.ClientSession, url: str) -> tuple[int, Any, str]:
    async with session.get(url, allow_redirects=True) as resp:
        ctype = resp.headers.get("Content-Type", "")
        if resp.status >= 400:
            return resp.status, None, ctype
        text = await resp.text()
        if "json" in ctype or text[:1] in "{[":
            try:
                return resp.status, json.loads(text), ctype
            except json.JSONDecodeError:
                return resp.status, text, ctype
        return resp.status, text, ctype


def _sample_keys(obj: Any) -> str:
    if isinstance(obj, dict):
        parts = []
        for key, val in list(obj.items())[:20]:
            if isinstance(val, dict):
                parts.append(f"{key}{{{','.join(list(val.keys())[:8])}}}")
            elif isinstance(val, list):
                inner = val[0] if val else None
                if isinstance(inner, dict):
                    parts.append(f"{key}[{','.join(list(inner.keys())[:8])}]")
                else:
                    parts.append(f"{key}[{type(inner).__name__ if inner is not None else 'empty'}]")
            else:
                shown = str(val)
                if len(shown) > 24:
                    shown = shown[:24] + "…"
                parts.append(f"{key}={shown}")
        return " | ".join(parts)
    return type(obj).__name__


def _first_list_item(payload: dict, keys: tuple[str, ...]) -> Any:
    for key in keys:
        val = payload.get(key)
        if isinstance(val, list) and val:
            return val[0]
        if isinstance(val, dict):
            for nested in val.values():
                if isinstance(nested, list) and nested:
                    return nested[0]
    return None


def _parse_attendance_html(html: str) -> list[LessonNote]:
    notes: list[LessonNote] = []
    for title, extra in re.findall(
        r'(?:title|aria-label|data-original-title)="([^"]{2,120})"[^>]{0,200}?(?:data-(?:code|type|caption)="([^"]*)")?',
        html,
        flags=re.IGNORECASE,
    ):
        blob = f"{title} {extra}".lower()
        if not any(
            token in blob
            for token in ("poissa", "myöh", "lupa", "selvitys", "sairas", "kehu", "kiitos", "huom", "terveys", "luvall")
        ):
            continue
        date_s = ""
        match = DATE_RE.search(title)
        if match:
            parsed = parse_date(match.group(1))
            date_s = parsed.isoformat() if parsed else match.group(1)
        notes.append(LessonNote(date=date_s, kind=title.strip(), text=(extra or "").strip()))
    for date_s, kind, extra in re.findall(
        r"(" + DATE_RE.pattern + r").{0,160}?(Poissa|Myöhässä|Lupa|Selvitys|Sairaana|Huomautus|Kehu|Kiitos|Myöh)([^<]{0,100})",
        html,
        flags=re.IGNORECASE,
    ):
        parsed = parse_date(date_s)
        notes.append(
            LessonNote(
                date=parsed.isoformat() if parsed else date_s,
                kind=kind,
                text=extra.strip(" :-·|"),
            )
        )
    return notes


def _apply_identity(payload: dict, data: SchoolData) -> None:
    name = _pick(payload, ("StudentName", "FullName", "Name", "name", "Caption", "caption"))
    if name and name.lower() not in {"wilma", "guardian", "huoltaja"} and not name.startswith("!"):
        data.child_name = data.child_name or name
    school = _pick(payload, ("SchoolName", "School", "school", "SchoolCaption"))
    if school:
        data.school_name = data.school_name or school
    klass = _pick(payload, ("ClassName", "Class", "Form", "Luokka", "className"))
    if klass:
        data.class_name = data.class_name or klass
    roles = payload.get("Roles") or payload.get("roles") or payload.get("Students")
    if isinstance(roles, list):
        for role in roles:
            if not isinstance(role, dict):
                continue
            role_name = _pick(role, ("Name", "name", "Caption", "StudentName", "FullName"))
            role_id = str(role.get("Id") or role.get("id") or role.get("PrimusId") or "")
            if role_name:
                data.child_name = data.child_name or role_name
                data.children = [Child(user_id=role_id or data.children[0].user_id if data.children else role_id, name=role_name)]
            data.school_name = data.school_name or _pick(role, ("SchoolName", "School"))
            data.class_name = data.class_name or _pick(role, ("ClassName", "Class", "Form"))
            break


def _parse_payload(payload: Any, data: SchoolData, source: str = "") -> None:
    if isinstance(payload, str) and (
        "Päällekkäinen kirjautuminen" in payload or "error-access-denied" in payload
    ):
        data.probes.append(f"{source} LOGIN_COLLISION")
        return
    if isinstance(payload, dict):
        _apply_identity(payload, data)
        if not data.overview_keys:
            data.overview_keys = ", ".join(list(payload.keys())[:40])
            data.sample_lesson = _sample_keys(
                _first_list_item(payload, ("Schedule", "schedule", "Lessons", "lessons", "Reservations"))
            )
            data.sample_exam = _sample_keys(
                _first_list_item(payload, ("Exams", "exams", "UpcomingExams", "upcomingExams"))
            )
            data.sample_hw = _sample_keys(_first_list_item(payload, ("Homework", "homework")))
            if not data.sample_hw:
                groups = payload.get("Groups") or payload.get("groups")
                if isinstance(groups, list) and groups and isinstance(groups[0], dict):
                    data.sample_hw = _sample_keys(groups[0])
        if not source.startswith("attendance"):
            _walk_lessons(payload, data.schedule)
            data.schedule = _dedupe_lessons(data.schedule)
            if not data.class_name:
                for slot in payload.get("Schedule") or payload.get("schedule") or []:
                    if isinstance(slot, dict):
                        klass = str(slot.get("Class") or "").strip()
                        if klass:
                            data.class_name = klass
                            break
            exam_src = (
                payload.get("Exams")
                or payload.get("exams")
                or payload.get("UpcomingExams")
                or payload.get("upcomingExams")
                or payload
            )
            _walk_exams(exam_src, data.exams, data.grades)
            walked_hw = False
            for key in ("Homework", "homework", "Groups", "groups", "Schedule", "schedule"):
                src = payload.get(key)
                if src:
                    _walk_homework(src, data.homework)
                    walked_hw = True
            if not walked_hw:
                _walk_homework(payload, data.homework)
            data.homework = _dedupe_homework(data.homework)
            # Extract courses from Groups
            for grp in payload.get("Groups") or payload.get("groups") or []:
                if not isinstance(grp, dict):
                    continue
                cname = _pick(grp, ("CourseName", "courseName", "FullCaption", "Caption"))
                ccode = _pick(grp, ("CourseCode", "courseCode", "ShortCaption"))
                teacher = _pick(grp, TEACHER_KEYS)
                if not teacher:
                    teachers = grp.get("Teachers") or []
                    if isinstance(teachers, list) and teachers and isinstance(teachers[0], dict):
                        t = teachers[0]
                        teacher = str(t.get("TeacherName") or t.get("LongCaption") or _as_text(t) or "")
                if cname or ccode:
                    data.courses.append(Course(
                        name=cname, code=ccode, teacher=teacher,
                        start=str(grp.get("StartDate") or ""),
                        end=str(grp.get("EndDate") or ""),
                    ))
                # Extract class name from group Class field
                klass = str(grp.get("Class") or "").strip()
                if klass and not data.class_name:
                    data.class_name = klass
            for item in payload.get("News") or payload.get("news") or []:
                if isinstance(item, dict):
                    data.news.append(
                        NewsItem(
                            id=str(item.get("Id") or item.get("id") or ""),
                            title=_as_text(item.get("Subject") or item.get("Title") or item.get("caption")),
                            date=_first_date(item),
                        )
                    )
        return
    if isinstance(payload, str):
        if not data.child_name:
            match = re.search(
                r'(?:selected-role|role-name|student-name|nav-user)[^>]*>\s*([^<]{2,60})',
                payload,
                flags=re.IGNORECASE,
            )
            if match:
                candidate = re.sub(r"\s+", " ", match.group(1)).strip()
                if candidate.lower() not in {"wilma", "huoltaja", "kirjaudu ulos"}:
                    data.child_name = candidate
        if source.startswith("attendance"):
            parsed_notes = _parse_attendance_html(payload)
            data.notes.extend(parsed_notes)
            titles = re.findall(r'title="([^"]{2,80})"', payload, flags=re.IGNORECASE)
            interesting = [
                t for t in titles if any(x in t.lower() for x in ("poissa", "myöh", "lupa", "sel", "kehu"))
            ]
            if interesting and not data.sample_note:
                data.sample_note = " || ".join(interesting[:8])


async def load_school(session: aiohttp.ClientSession, base_url: str, user_id: str) -> SchoolData:
    data = SchoolData()
    data.children.append(Child(user_id=user_id))
    for path in PROBE_PATHS:
        url = _abs(base_url, user_id, path)
        try:
            status, payload, ctype = await _get(session, url)
        except Exception as err:  # noqa: BLE001
            data.probes.append(f"{path} ERR {err}")
            continue
        data.probes.append(f"{path} {status} {ctype.split(';')[0]}")
        if status != 200 or payload is None:
            continue
        before = len(data.notes)
        _parse_payload(payload, data, path)
        if len(data.notes) > before or isinstance(payload, dict):
            data.sources.append(path)
    data.notes = _dedupe_notes(data.notes)
    data.homework = _dedupe_homework(data.homework)
    data.sources = list(dict.fromkeys(data.sources))
    return data


def lessons_for_day(schedule: list[Lesson], target: date) -> list[Lesson]:
    weekday = target.isoweekday()
    iso = target.isoformat()
    out: list[Lesson] = []
    for lesson in schedule:
        dates = {parse_date(item).isoformat() for item in lesson.dates if parse_date(item)}
        if iso in dates or (lesson.date and parse_date(lesson.date) == target):
            out.append(lesson)
        elif not dates and not lesson.date and lesson.day == weekday:
            out.append(lesson)
    out.sort(key=lambda item: item.start or "")
    return out


def next_lesson(schedule: list[Lesson], now: datetime | None = None) -> Lesson | None:
    now = now or datetime.now(ZoneInfo(TIMEZONE))
    today = now.date()
    for offset in range(0, 8):
        day = today + timedelta(days=offset)
        for lesson in lessons_for_day(schedule, day):
            start = parse_time(lesson.start)
            if offset == 0 and start and datetime.combine(day, start, tzinfo=now.tzinfo) <= now:
                continue
            lesson.date = day.isoformat()
            return lesson
    return None
