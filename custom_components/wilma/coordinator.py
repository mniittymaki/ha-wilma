"""Wilma coordinator — one login per guardian account."""
from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import timedelta
import logging

import aiohttp
from wilhelmina import AuthenticationError, WilmaClient, WilmaError

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import load_school
from .const import (
    BROWSER_HEADERS,
    CONF_CHILD_ID,
    CONF_CHILD_NAME,
    CONF_CHILDREN,
    CONF_PASSWORD,
    CONF_SCAN_INTERVAL,
    CONF_URL,
    CONF_USERNAME,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
)
from .models import SchoolData
from .roles import switch_child

_LOGGER = logging.getLogger(__name__)


def account_key(entry: ConfigEntry) -> str:
    return f"{entry.data[CONF_URL]}:{entry.data[CONF_USERNAME].lower()}"


def children_from_entry(entry: ConfigEntry) -> list[dict[str, str]]:
    raw = entry.data.get(CONF_CHILDREN)
    if isinstance(raw, list) and raw:
        out = []
        for item in raw:
            if isinstance(item, dict) and item.get("id"):
                out.append({"id": str(item["id"]), "name": str(item.get("name") or item["id"])})
        if out:
            return out
    child_id = entry.data.get(CONF_CHILD_ID) or ""
    if child_id:
        return [{"id": str(child_id), "name": str(entry.data.get(CONF_CHILD_NAME) or child_id)}]
    return []


@dataclass
class WilmaMessage:
    id: int
    subject: str
    sender: str
    timestamp: str
    unread: bool


@dataclass
class WilmaData:
    unread: int
    count: int
    messages: list[WilmaMessage]
    latest: WilmaMessage | None
    school: SchoolData
    schools: dict[str, SchoolData] = field(default_factory=dict)


def _account_lock(hass: HomeAssistant, key: str) -> asyncio.Lock:
    store = hass.data.setdefault(DOMAIN, {}).setdefault("_locks", {})
    if key not in store:
        store[key] = asyncio.Lock()
    return store[key]


class WilmaCoordinator(DataUpdateCoordinator[WilmaData]):
    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        interval = entry.data.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)
        super().__init__(hass, _LOGGER, name=DOMAIN, update_interval=timedelta(seconds=interval))
        self.entry = entry
        self._session: aiohttp.ClientSession | None = None
        self.client: WilmaClient | None = None
        self._logged_in = False
        self._known_unread_ids: set[int] = set()

    async def async_setup(self) -> None:
        self._session = aiohttp.ClientSession(headers=BROWSER_HEADERS)
        self.client = WilmaClient(self.entry.data[CONF_URL], session=self._session, headless=True)

    async def async_shutdown(self) -> None:
        if self._session and not self._session.closed:
            await self._session.close()
        self._session = None
        self.client = None
        self._logged_in = False

    async def async_login(self) -> None:
        assert self.client is not None
        await self.client.login(self.entry.data[CONF_USERNAME], self.entry.data[CONF_PASSWORD])
        self._logged_in = True

    async def _fetch_messages(self):
        assert self.client is not None
        try:
            if not self._logged_in:
                await self.async_login()
            return await self.client.get_messages()
        except AuthenticationError as err:
            if _transient(err):
                raise
            self._logged_in = False
            await self.async_login()
            return await self.client.get_messages()

    async def _async_update_data(self) -> WilmaData:
        assert self.client is not None
        assert self._session is not None
        lock = _account_lock(self.hass, account_key(self.entry))
        async with lock:
            try:
                raw = await self._fetch_messages()
            except AuthenticationError as err:
                if _transient(err):
                    raise UpdateFailed(f"Wilma temporarily unavailable: {err}") from err
                raise ConfigEntryAuthFailed(str(err)) from err
            except WilmaError as err:
                raise UpdateFailed(str(err)) from err

            messages = [
                WilmaMessage(
                    id=int(getattr(msg, "id", 0) or 0),
                    subject=str(getattr(msg, "subject", "") or ""),
                    sender=str(getattr(msg, "sender", "") or ""),
                    timestamp=str(getattr(msg, "timestamp", "") or ""),
                    unread=bool(getattr(msg, "unread", False)),
                )
                for msg in raw
            ]
            unread_msgs = [msg for msg in messages if msg.unread]

            schools: dict[str, SchoolData] = {}
            kids = children_from_entry(self.entry)
            if not kids:
                uid = getattr(self.client, "user_id", None)
                if uid:
                    kids = [{"id": str(uid), "name": str(uid)}]
            for index, kid in enumerate(kids):
                if index:
                    await asyncio.sleep(1)
                try:
                    await switch_child(self._session, self.entry.data[CONF_URL], kid["id"])
                    school = await load_school(self._session, self.entry.data[CONF_URL], kid["id"])
                except Exception as err:  # noqa: BLE001
                    _LOGGER.warning("Wilma school fetch failed for %s: %s", kid["id"], err)
                    school = SchoolData()
                    school.probes.append(f"load_school ERR {err}")
                school.child_name = kid["name"]
                schools[kid["id"]] = school

            first = next(iter(schools.values()), SchoolData())
            self._notify_new(unread_msgs)
            return WilmaData(
                unread=len(unread_msgs),
                count=len(messages),
                messages=messages[:20],
                latest=messages[0] if messages else None,
                school=first,
                schools=schools,
            )

    def _notify_new(self, unread_msgs: list[WilmaMessage]) -> None:
        current = {msg.id for msg in unread_msgs if msg.id}
        new_ids = current - self._known_unread_ids
        if not self._known_unread_ids:
            self._known_unread_ids = current
            return
        self._known_unread_ids = current
        for msg in unread_msgs:
            if msg.id not in new_ids:
                continue
            self.hass.async_create_task(
                self.hass.services.async_call(
                    "persistent_notification",
                    "create",
                    {
                        "title": f"Wilma: {msg.subject}",
                        "message": f"{msg.sender}\n{msg.timestamp}",
                        "notification_id": f"wilma_{msg.id}",
                    },
                    blocking=False,
                )
            )


def _transient(err: Exception) -> bool:
    text = str(err).lower()
    return any(token in text for token in ("521", "502", "503", "504", "429", "timeout", "temporar"))
