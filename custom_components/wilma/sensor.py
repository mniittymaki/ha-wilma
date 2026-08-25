"""Wilma sensors."""
from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from homeassistant.components.sensor import SensorEntity, SensorStateClass
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .api import lessons_for_day, next_lesson, parse_date
from .const import CONF_CHILD_ID, CONF_CHILD_NAME, DOMAIN, TIMEZONE
from .coordinator import WilmaCoordinator, WilmaData


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback) -> None:
    coordinator: WilmaCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(
        [
            StatusSensor(coordinator, entry),
            UnreadSensor(coordinator, entry),
            LatestMessageSensor(coordinator, entry),
            MessageCountSensor(coordinator, entry),
            AbsenceSensor(coordinator, entry),
            LateSensor(coordinator, entry),
            PositiveSensor(coordinator, entry),
            LatestNoteSensor(coordinator, entry),
            TodaySensor(coordinator, entry),
            NextLessonSensor(coordinator, entry),
            HomeworkSensor(coordinator, entry),
            ExamSensor(coordinator, entry),
            GradeSensor(coordinator, entry),
            NewsSensor(coordinator, entry),
            CourseSensor(coordinator, entry),
        ]
    )


def _join(*parts: str) -> str:
    return " · ".join(part for part in parts if part)


class Base(CoordinatorEntity[WilmaCoordinator], SensorEntity):
    _attr_has_entity_name = True

    def __init__(self, coordinator: WilmaCoordinator, entry: ConfigEntry, uid: str) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{entry.entry_id}_{uid}"
        self._entry = entry
        child = entry.data.get(CONF_CHILD_NAME) or entry.title
        self._attr_device_info = {
            "identifiers": {(DOMAIN, entry.entry_id)},
            "name": child,
            "manufacturer": "Visma",
            "model": entry.data.get(CONF_CHILD_ID) or "Wilma",
        }

    @property
    def data(self) -> WilmaData | None:
        return self.coordinator.data

    @property
    def school(self):
        return None if not self.data else self.data.school


class StatusSensor(Base):
    _attr_name = "Oppilas"
    _attr_icon = "mdi:account-school"

    def __init__(self, coordinator, entry):
        super().__init__(coordinator, entry, "student")

    @property
    def native_value(self) -> str:
        school = self.school
        if not school:
            return "Wilma"
        return school.child_name or school.class_name or self._entry.data.get(CONF_CHILD_NAME) or "Wilma"

    @property
    def extra_state_attributes(self) -> dict:
        school = self.school
        if not school:
            return {}
        return {
            "child": self._entry.data.get(CONF_CHILD_NAME),
            "child_id": self._entry.data.get(CONF_CHILD_ID),
            "school": school.school_name,
            "class": school.class_name,
            "children": ", ".join(f"{c.name or c.user_id}" for c in school.children),
            "sources": ", ".join(school.sources),
            "probes": school.probes,
            "notes": len(school.notes),
            "lessons": len(school.schedule),
            "homework": len(school.homework),
            "exams": len(school.exams),
            "news": len(school.news),
            "overview_keys": school.overview_keys,
            "sample_lesson": school.sample_lesson,
            "sample_note": school.sample_note,
            "sample_exam": school.sample_exam,
            "sample_hw": school.sample_hw,
        }


class UnreadSensor(Base):
    _attr_name = "Lukemattomat"
    _attr_icon = "mdi:email-alert"
    _attr_native_unit_of_measurement = "kpl"
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, coordinator, entry):
        super().__init__(coordinator, entry, "unread")

    @property
    def native_value(self) -> int:
        return 0 if not self.data else self.data.unread


class MessageCountSensor(Base):
    _attr_name = "Viestit"
    _attr_icon = "mdi:email-multiple"
    _attr_native_unit_of_measurement = "kpl"
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, coordinator, entry):
        super().__init__(coordinator, entry, "count")

    @property
    def native_value(self) -> int:
        return 0 if not self.data else self.data.count


class LatestMessageSensor(Base):
    _attr_name = "Viimeisin viesti"
    _attr_icon = "mdi:email"

    def __init__(self, coordinator, entry):
        super().__init__(coordinator, entry, "latest")

    @property
    def native_value(self) -> str:
        if not self.data or not self.data.latest:
            return "Ei viestejä"
        return self.data.latest.subject

    @property
    def extra_state_attributes(self) -> dict:
        if not self.data:
            return {}
        attrs = {"unread": self.data.unread, "count": self.data.count}
        if self.data.latest:
            attrs.update(
                sender=self.data.latest.sender,
                timestamp=self.data.latest.timestamp,
                message_id=self.data.latest.id,
            )
        for i, msg in enumerate(self.data.messages[:10], start=1):
            flag = "● " if msg.unread else ""
            attrs[f"msg_{i}"] = f"{flag}{msg.subject} · {msg.sender}"
        return attrs


class AbsenceSensor(Base):
    _attr_name = "Poissaolot"
    _attr_icon = "mdi:account-off"
    _attr_native_unit_of_measurement = "kpl"
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, coordinator, entry):
        super().__init__(coordinator, entry, "absences")

    @property
    def native_value(self) -> int:
        return 0 if not self.school else len(self.school.absences)

    @property
    def extra_state_attributes(self) -> dict:
        if not self.school:
            return {}
        return {
            f"item_{i}": _join(n.date, n.kind or n.code, n.subject, n.teacher, n.text)
            for i, n in enumerate(self.school.absences[:15], start=1)
        }


class LateSensor(Base):
    _attr_name = "Myöhästymiset"
    _attr_icon = "mdi:clock-alert"
    _attr_native_unit_of_measurement = "kpl"
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, coordinator, entry):
        super().__init__(coordinator, entry, "late")

    @property
    def native_value(self) -> int:
        return 0 if not self.school else len(self.school.lates)

    @property
    def extra_state_attributes(self) -> dict:
        if not self.school:
            return {}
        return {
            f"item_{i}": _join(n.date, n.kind or n.code, n.subject, n.text)
            for i, n in enumerate(self.school.lates[:15], start=1)
        }


class PositiveSensor(Base):
    _attr_name = "Kehut"
    _attr_icon = "mdi:thumb-up"
    _attr_native_unit_of_measurement = "kpl"
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, coordinator, entry):
        super().__init__(coordinator, entry, "positives")

    @property
    def native_value(self) -> int:
        return 0 if not self.school else len(self.school.positives)

    @property
    def extra_state_attributes(self) -> dict:
        if not self.school:
            return {}
        return {
            f"item_{i}": _join(n.date, n.kind, n.subject, n.text)
            for i, n in enumerate(self.school.positives[:10], start=1)
        }


class LatestNoteSensor(Base):
    _attr_name = "Viimeisin tuntimerkintä"
    _attr_icon = "mdi:notebook"

    def __init__(self, coordinator, entry):
        super().__init__(coordinator, entry, "latest_note")

    @property
    def native_value(self) -> str:
        notes = self.school.notes if self.school else []
        if not notes:
            return "Ei merkintöjä"
        note = notes[0]
        return _join(note.date, note.kind or note.code, note.subject) or "Merkintä"

    @property
    def extra_state_attributes(self) -> dict:
        if not self.school:
            return {}
        attrs = {"note_count": len(self.school.notes)}
        for i, note in enumerate(self.school.notes[:20], start=1):
            attrs[f"note_{i}"] = _join(note.date, note.time, note.kind or note.code, note.subject, note.teacher, note.text)
        return attrs


class TodaySensor(Base):
    _attr_name = "Tänään"
    _attr_icon = "mdi:calendar-today"

    def __init__(self, coordinator, entry):
        super().__init__(coordinator, entry, "today")

    def _today(self):
        if not self.school:
            return []
        return lessons_for_day(self.school.schedule, datetime.now(ZoneInfo(TIMEZONE)).date())

    @property
    def native_value(self) -> str:
        lessons = self._today()
        if not lessons:
            return "Ei tunteja"
        first, last = lessons[0], lessons[-1]
        return _join(f"{len(lessons)} tuntia", first.start, last.end)

    @property
    def extra_state_attributes(self) -> dict:
        attrs = {}
        for i, lesson in enumerate(self._today(), start=1):
            attrs[f"lesson_{i}"] = _join(lesson.start, lesson.end, lesson.subject, lesson.teacher, lesson.room)
        return attrs


class NextLessonSensor(Base):
    _attr_name = "Seuraava tunti"
    _attr_icon = "mdi:calendar-clock"

    def __init__(self, coordinator, entry):
        super().__init__(coordinator, entry, "next_lesson")

    @property
    def native_value(self) -> str:
        if not self.school:
            return "Ei lukujärjestystä"
        lesson = next_lesson(self.school.schedule)
        if not lesson:
            return "Ei lukujärjestystä"
        return _join(lesson.date, lesson.start, lesson.subject, lesson.room) or "Tunti"

    @property
    def extra_state_attributes(self) -> dict:
        if not self.school:
            return {}
        attrs = {}
        for i, lesson in enumerate(self.school.schedule[:16], start=1):
            attrs[f"lesson_{i}"] = _join(
                str(lesson.day) if lesson.day else "",
                lesson.start,
                lesson.end,
                lesson.subject,
                lesson.teacher,
                lesson.room,
            )
        return attrs


class HomeworkSensor(Base):
    _attr_name = "Läksyt"
    _attr_icon = "mdi:book-education"
    _attr_native_unit_of_measurement = "kpl"
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, coordinator, entry):
        super().__init__(coordinator, entry, "homework")

    @property
    def native_value(self) -> int:
        return 0 if not self.school else len(self.school.homework)

    @property
    def extra_state_attributes(self) -> dict:
        if not self.school:
            return {}
        return {
            f"hw_{i}": _join(item.date, item.subject, item.text)
            for i, item in enumerate(self.school.homework[:12], start=1)
        }


class ExamSensor(Base):
    _attr_name = "Seuraava koe"
    _attr_icon = "mdi:file-document-edit"

    def __init__(self, coordinator, entry):
        super().__init__(coordinator, entry, "exam")

    def _upcoming(self):
        today = datetime.now(ZoneInfo(TIMEZONE)).date()
        exams = []
        for exam in self.school.exams if self.school else []:
            parsed = parse_date(exam.date)
            if parsed is None or parsed >= today:
                exams.append(exam)
        exams.sort(key=lambda item: parse_date(item.date) or datetime.max.date())
        return exams

    @property
    def native_value(self) -> str:
        exams = self._upcoming()
        if not exams:
            return "Ei kokeita"
        exam = exams[0]
        return _join(exam.date, exam.subject, exam.name) or "Koe"

    @property
    def extra_state_attributes(self) -> dict:
        return {
            f"exam_{i}": _join(exam.date, exam.subject, exam.name, exam.topic)
            for i, exam in enumerate(self._upcoming()[:8], start=1)
        }


class GradeSensor(Base):
    _attr_name = "Arvosanat"
    _attr_icon = "mdi:school"
    _attr_native_unit_of_measurement = "kpl"
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, coordinator, entry):
        super().__init__(coordinator, entry, "grades")

    @property
    def native_value(self) -> int:
        return 0 if not self.school else len(self.school.grades)

    @property
    def extra_state_attributes(self) -> dict:
        if not self.school:
            return {}
        return {
            f"grade_{i}": _join(item.date, item.subject, item.grade, item.name)
            for i, item in enumerate(self.school.grades[:12], start=1)
        }


class NewsSensor(Base):
    _attr_name = "Tiedote"
    _attr_icon = "mdi:bullhorn"

    def __init__(self, coordinator, entry):
        super().__init__(coordinator, entry, "news")

    @property
    def native_value(self) -> str:
        news = self.school.news if self.school else []
        return news[0].title if news else "Ei tiedotteita"

    @property
    def extra_state_attributes(self) -> dict:
        if not self.school:
            return {}
        return {
            f"news_{i}": _join(item.date, item.title)
            for i, item in enumerate(self.school.news[:8], start=1)
        }


class CourseSensor(Base):
    _attr_name = "Kurssit"
    _attr_icon = "mdi:bookshelf"
    _attr_native_unit_of_measurement = "kpl"
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, coordinator, entry):
        super().__init__(coordinator, entry, "courses")

    @property
    def native_value(self) -> int:
        return 0 if not self.school else len(self.school.courses)

    @property
    def extra_state_attributes(self) -> dict:
        if not self.school:
            return {}
        return {
            f"course_{i}": _join(item.code, item.name, item.teacher)
            for i, item in enumerate(self.school.courses[:16], start=1)
        }
