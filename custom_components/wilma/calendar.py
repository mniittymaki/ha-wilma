"""Wilma calendar: lessons, exams and homework dates."""
from __future__ import annotations

from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from homeassistant.components.calendar import CalendarEntity, CalendarEvent
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .api import parse_date, parse_time
from .const import DOMAIN, TIMEZONE
from .coordinator import WilmaCoordinator, children_from_entry

_TZ = ZoneInfo(TIMEZONE)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback) -> None:
    coordinator: WilmaCoordinator = hass.data[DOMAIN][entry.entry_id]
    kids = children_from_entry(entry)
    if not kids:
        async_add_entities([WilmaCalendar(coordinator, entry)])
        return
    async_add_entities([WilmaCalendar(coordinator, entry, kid["id"], kid["name"]) for kid in kids])


class WilmaCalendar(CoordinatorEntity[WilmaCoordinator], CalendarEntity):
    _attr_has_entity_name = True
    _attr_name = "Kalenteri"
    _attr_icon = "mdi:calendar-school"

    def __init__(
        self,
        coordinator: WilmaCoordinator,
        entry: ConfigEntry,
        child_id: str | None = None,
        child_name: str | None = None,
    ) -> None:
        super().__init__(coordinator)
        self._child_id = child_id or ""
        suffix = f"_{child_id}" if child_id else ""
        self._attr_unique_id = f"{entry.entry_id}_calendar{suffix}"
        self._attr_device_info = {
            "identifiers": {(DOMAIN, f"{entry.entry_id}:{child_id}" if child_id else entry.entry_id)},
            "name": child_name or entry.title,
            "manufacturer": "Visma",
            "model": child_id or "Wilma",
        }

    @property
    def event(self) -> CalendarEvent | None:
        now = datetime.now(_TZ)
        upcoming = [
            item
            for item in self._events(now.date(), now.date() + timedelta(days=7))
            if _event_end(item) >= now
        ]
        upcoming.sort(key=lambda item: _event_start(item))
        return upcoming[0] if upcoming else None

    async def async_get_events(self, hass: HomeAssistant, start_date: datetime, end_date: datetime) -> list[CalendarEvent]:
        return self._events(start_date.date(), end_date.date())

    def _events(self, start: date, end: date) -> list[CalendarEvent]:
        data = self.coordinator.data
        if not data:
            return []
        school = data.schools.get(self._child_id) if self._child_id and data.schools else data.school
        events: list[CalendarEvent] = []

        cursor = start
        while cursor <= end:
            weekday = cursor.isoweekday()
            iso = cursor.isoformat()
            for lesson in school.schedule:
                dates = {parse_date(item).isoformat() for item in lesson.dates if parse_date(item)}
                matches = iso in dates or (lesson.date and parse_date(lesson.date) == cursor)
                if not matches and not dates and not lesson.date and lesson.day == weekday:
                    matches = True
                if not matches:
                    continue
                events.append(
                    _timed(
                        cursor,
                        lesson.start,
                        lesson.end,
                        lesson.subject or "Tunti",
                        " · ".join(p for p in (lesson.teacher, lesson.room) if p),
                    )
                )
            cursor += timedelta(days=1)

        for exam in school.exams:
            parsed = parse_date(exam.date)
            if parsed and start <= parsed <= end:
                events.append(
                    CalendarEvent(
                        start=parsed,
                        end=parsed + timedelta(days=1),
                        summary=f"Koe: {exam.subject or exam.name}".strip(),
                        description=exam.topic or exam.name,
                    )
                )
        for item in school.homework:
            parsed = parse_date(item.date)
            if parsed and start <= parsed <= end:
                events.append(
                    CalendarEvent(
                        start=parsed,
                        end=parsed + timedelta(days=1),
                        summary=f"Läksy: {item.subject}".strip(),
                        description=item.text,
                    )
                )
        return events


def _as_datetime(value: date | datetime, *, end: bool = False) -> datetime:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=_TZ)
    moment = time.max if end else time.min
    return datetime.combine(value, moment, tzinfo=_TZ)


def _event_start(item: CalendarEvent) -> datetime:
    return _as_datetime(item.start)


def _event_end(item: CalendarEvent) -> datetime:
    return _as_datetime(item.end, end=True)


def _timed(day: date, start_s: str, end_s: str, summary: str, description: str) -> CalendarEvent:
    start_t = parse_time(start_s) or time(8, 0)
    end_t = parse_time(end_s)
    start = datetime.combine(day, start_t, tzinfo=_TZ)
    if end_t is None:
        end = start + timedelta(hours=1)
    else:
        end = datetime.combine(day, end_t, tzinfo=_TZ)
    if end <= start:
        end = start + timedelta(minutes=45)
    return CalendarEvent(start=start, end=end, summary=summary, description=description)
