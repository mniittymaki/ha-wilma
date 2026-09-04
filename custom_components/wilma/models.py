"""Wilma data models."""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Child:
    user_id: str
    name: str = ""
    school: str = ""
    class_name: str = ""


@dataclass
class LessonNote:
    date: str = ""
    time: str = ""
    subject: str = ""
    teacher: str = ""
    kind: str = ""
    text: str = ""
    code: str = ""


@dataclass
class Lesson:
    day: int = 0
    date: str = ""
    start: str = ""
    end: str = ""
    subject: str = ""
    teacher: str = ""
    room: str = ""
    dates: list[str] = field(default_factory=list)


@dataclass
class Homework:
    subject: str = ""
    text: str = ""
    date: str = ""
    teacher: str = ""


@dataclass
class Exam:
    subject: str = ""
    date: str = ""
    name: str = ""
    grade: str = ""
    seen: bool = False
    teacher: str = ""
    topic: str = ""


@dataclass
class NewsItem:
    id: str = ""
    title: str = ""
    date: str = ""
    summary: str = ""


@dataclass
class Course:
    name: str = ""
    code: str = ""
    teacher: str = ""
    start: str = ""
    end: str = ""


@dataclass
class SchoolData:
    children: list[Child] = field(default_factory=list)
    notes: list[LessonNote] = field(default_factory=list)
    schedule: list[Lesson] = field(default_factory=list)
    homework: list[Homework] = field(default_factory=list)
    exams: list[Exam] = field(default_factory=list)
    grades: list[Exam] = field(default_factory=list)
    news: list[NewsItem] = field(default_factory=list)
    courses: list[Course] = field(default_factory=list)
    sources: list[str] = field(default_factory=list)
    probes: list[str] = field(default_factory=list)
    child_name: str = ""
    school_name: str = ""
    class_name: str = ""
    overview_keys: str = ""
    sample_lesson: str = ""
    sample_note: str = ""
    sample_exam: str = ""
    sample_hw: str = ""

    @property
    def absences(self) -> list[LessonNote]:
        return [n for n in self.notes if _match(n, ABSENCE)]

    @property
    def unresolved(self) -> list[LessonNote]:
        return [n for n in self.notes if _match(n, UNRESOLVED)]

    @property
    def lates(self) -> list[LessonNote]:
        return [n for n in self.notes if _match(n, LATE)]

    @property
    def positives(self) -> list[LessonNote]:
        return [n for n in self.notes if _match(n, POSITIVE)]

    @property
    def unread_grades(self) -> list[Exam]:
        return [grade for grade in self.grades if not grade.seen]


ABSENCE = (
    "poissa",
    "absent",
    "selvitys",
    "selvitettävä",
    "sairas",
    "sairaana",
    "lupa",
    "luvallinen",
    "terveys",
    "terveydellinen",
    "sel",
    "ter",
    "lup",
)
LATE = ("myöh", "late", "tardy", "myö")
POSITIVE = ("kehu", "kiitos", "aktiiv", "+akt", "+teh", "+koe", "hyvä")
UNRESOLVED = ("selvittämätön", "selvitettävä", "selvittämättä", "unresolved", "unexcused")


def _match(note: LessonNote, tokens: tuple[str, ...]) -> bool:
    blob = f"{note.kind} {note.text} {note.code}".lower()
    return any(token in blob for token in tokens)
