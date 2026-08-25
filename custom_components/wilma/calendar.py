"""Wilma calendar: lessons, exams and homework dates."""
from __future__ import annotations

from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from homeassistant.components.calendar import CalendarEntity, CalendarEvent
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .api import parse_date, parse_time
from .const import DOMAIN, TIMEZONE
from .coordinator import WilmaCoordinator

_TZ = ZoneInfo(TIMEZONE)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback) -> None:
    coordinator: WilmaCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([WilmaCalendar(coordinator, entry)])


class WilmaCalendar(CoordinatorEntity[WilmaCoordinator], CalendarEntity):
    _attr_has_entity_name = True
    _attr_name = "Kalenteri"
    _attr_icon = "mdi:calendar-school"

    def __init__(self, coordinator: WilmaCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{entry.entry_id}_calendar"
        self._attr_device_info = {
            "identifiers": {(DOMAIN, entry.entry_id)},
            "name": entry.title,
            "manufacturer": "Visma",
            "model": "Wilma",
        }

    @property
    def event(self) -> CalendarEvent | None:
        now = datetime.now(_TZ)
        upcoming = [item for item in self._events(now.date(), now.date() + timedelta(days=7)) if item.end >= now]
        upcoming.sort(key=lambda item: item.start)
        return upcoming[0] if upcoming else None

    async def async_get_events(self, hass: HomeAssistant, start_date: datetime, end_date: datetime) -> list[CalendarEvent]:
        return self._events(start_date.date(), end_date.date())

    def _events(self, start: date, end: date) -> list[CalendarEvent]:
        data = self.coordinator.data
        if not data:
            return []
        school = data.school
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


def _timed(day: date, start_s: str, end_s: str, summary: str, description: str) -> CalendarEvent:
    start_hm = parse_time(start_s) or (8, 0)
    end_hm = parse_time(end_s) or (start_hm[0] + 1, start_hm[1])
    start = datetime(day.year, day.month, day.day, start_hm[0], start_hm[1], tzinfo=_TZ)
    end = datetime(day.year, day.month, day.day, end_hm[0], end_hm[1], tzinfo=_TZ)
    if end <= start:
        end = start + timedelta(minutes=45)
    return CalendarEvent(start=start, end=end, summary=summary, description=description)
