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
from .messages import fetch_messages_html, fetch_messages_json, fetch_unread_ids
from .models import SchoolData
from .roles import _is_named_child, _norm_id, switch_child

_LOGGER = logging.getLogger(__name__)


def account_key(entry: ConfigEntry) -> str:
    return f"{entry.data[CONF_URL]}:{entry.data[CONF_USERNAME].lower()}"


def children_from_entry(entry: ConfigEntry) -> list[dict[str, str]]:
    raw = entry.data.get(CONF_CHILDREN)
    if isinstance(raw, list) and raw:
        found: dict[str, str] = {}
        for item in raw:
            if isinstance(item, dict) and item.get("id"):
                child_id = _norm_id(str(item["id"]))
                if child_id:
                    name = str(item.get("name") or child_id)
                    found[child_id] = name if name != child_id else found.get(child_id, name)
        out = [{"id": child_id, "name": name} for child_id, name in found.items()]
        named = [kid for kid in out if _is_named_child(kid["name"], kid["id"])]
        if named:
            return named
        if out:
            return out
    child_id = _norm_id(entry.data.get(CONF_CHILD_ID) or "")
    if child_id:
        return [{"id": child_id, "name": str(entry.data.get(CONF_CHILD_NAME) or child_id)}]
    return []


@dataclass
class WilmaMessage:
    id: int
    subject: str
    sender: str
    timestamp: str
    unread: bool


@dataclass
class ChildMessages:
    unread: int = 0
    count: int = 0
    messages: list[WilmaMessage] = field(default_factory=list)
    latest: WilmaMessage | None = None
    unread_source: str = ""


@dataclass
class WilmaData:
    unread: int
    count: int
    messages: list[WilmaMessage]
    latest: WilmaMessage | None
    school: SchoolData
    schools: dict[str, SchoolData] = field(default_factory=dict)
    child_messages: dict[str, ChildMessages] = field(default_factory=dict)
    unread_source: str = ""


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
        self._pin_role_across_reauth()

    def _pin_role_across_reauth(self) -> None:
        """Keep `user_id` on this entry's child even when Wilhelmina re-authenticates.

        `_authenticated_request` retries a 403 by calling `login()` again, which
        rewrites `user_id` back to the guardian role *mid-call* - so re-applying
        the override before each fetch is not enough, and that poll would report
        the guardian's inbox. Wrapping login covers the internal retry too.
        """
        assert self.client is not None
        inner_login = self.client.login

        async def login_and_pin(*args, **kwargs):
            await inner_login(*args, **kwargs)
            uid = self._child_uid()
            if uid and self.client is not None:
                self.client.user_id = uid

        self.client.login = login_and_pin

    async def async_shutdown(self) -> None:
        if self._session and not self._session.closed:
            await self._session.close()
        self._session = None
        self.client = None
        self._logged_in = False

    def _child_uid(self) -> str:
        """Normalised role id for the child this entry is configured for."""
        return _norm_id(self.entry.data.get(CONF_CHILD_ID) or "")

    def _apply_role(self) -> str:
        """Point the Wilhelmina client at this entry's child.

        `WilmaClient.login()` sets `user_id` from the post-login redirect, i.e.
        the guardian's default role, and `get_messages()` requests
        `{base}/{user_id}/messages/list`. Without this override every child
        entry would read the same inbox. `_authenticated_request` re-runs
        `login()` on an expired session, resetting the field, so this has to be
        re-applied before each fetch rather than only at login.
        """
        assert self.client is not None
        uid = self._child_uid()
        if uid:
            self.client.user_id = uid
        return uid or str(getattr(self.client, "user_id", "") or "")

    async def async_login(self) -> None:
        assert self.client is not None
        await self.client.login(self.entry.data[CONF_USERNAME], self.entry.data[CONF_PASSWORD])
        child_id = self.entry.data.get(CONF_CHILD_ID)
        if child_id and self._session:
            try:
                await switch_child(self._session, self.entry.data[CONF_URL], child_id)
            except Exception as err:  # noqa: BLE001
                _LOGGER.debug("Wilma role switch skipped: %s", err)
        self._apply_role()
        self._logged_in = True

    async def _fetch_messages(self):
        assert self.client is not None
        try:
            if not self._logged_in:
                await self.async_login()
            self._apply_role()
            return await self.client.get_messages()
        except AuthenticationError as err:
            if _transient(err):
                raise
            self._logged_in = False
            await self.async_login()
            self._apply_role()
            return await self.client.get_messages()

    async def _fetch_child_messages(self, child_id: str) -> list[WilmaMessage]:
        """Fetch messages for a specific child. JSON first, HTML fallback."""
        assert self._session is not None
        base = self.entry.data[CONF_URL]
        messages: list[WilmaMessage] = []

        # JSON messages/list (works after switch_child, has Status field)
        try:
            json_msgs = await fetch_messages_json(self._session, base, child_id)
            for m in json_msgs:
                messages.append(WilmaMessage(
                    id=m["id"], subject=m["subject"], sender=m["sender"],
                    timestamp=m["timestamp"], unread=m["unread"],
                ))
        except Exception as err:  # noqa: BLE001
            _LOGGER.debug("Wilma JSON messages failed for %s: %s", child_id, err)

        # HTML fallback if JSON returned nothing
        if not messages:
            try:
                html_msgs = await fetch_messages_html(self._session, base, child_id)
                for m in html_msgs:
                    messages.append(WilmaMessage(
                        id=m["id"], subject=m["subject"], sender=m["sender"],
                        timestamp=m["timestamp"], unread=m["unread"],
                    ))
            except Exception as err:  # noqa: BLE001
                _LOGGER.debug("Wilma HTML messages failed for %s: %s", child_id, err)

        return messages

    async def _load_child_school(self, child_id: str, child_name: str) -> SchoolData | None:
        """Fetch one child's school pages. Relogin + retry on collision / dead session.

        Returns None when both attempts fail so the caller can keep last data.
        """
        assert self._session is not None
        last_error: Exception | None = None
        for attempt in range(2):
            try:
                if attempt:
                    _LOGGER.info("Wilma relogin before retrying school fetch for %s", child_id)
                    self._logged_in = False
                    await self.async_login()
                await switch_child(self._session, self.entry.data[CONF_URL], child_id)
                school = await load_school(self._session, self.entry.data[CONF_URL], child_id)
            except Exception as err:  # noqa: BLE001
                last_error = err
                _LOGGER.warning(
                    "Wilma school fetch failed for %s (attempt %s): %s",
                    child_id,
                    attempt + 1,
                    err,
                )
                continue
            if _stale_school(school):
                _LOGGER.warning(
                    "Wilma school session stale for %s (attempt %s): %s",
                    child_id,
                    attempt + 1,
                    school.probes,
                )
                continue
            school.child_name = child_name or school.child_name
            return school
        if last_error:
            _LOGGER.warning("Wilma school fetch gave up for %s: %s", child_id, last_error)
        return None

    async def _async_update_data(self) -> WilmaData:
        assert self.client is not None
        assert self._session is not None
        lock = _account_lock(self.hass, account_key(self.entry))
        async with lock:
            if not self._logged_in:
                try:
                    await self.async_login()
                except AuthenticationError as err:
                    if _transient(err):
                        raise UpdateFailed(f"Wilma temporarily unavailable: {err}") from err
                    raise ConfigEntryAuthFailed(str(err)) from err

            unread_source = ""

            old_schools = dict(self.data.schools) if self.data and self.data.schools else {}
            schools: dict[str, SchoolData] = {}
            child_msgs: dict[str, ChildMessages] = {}
            failed: list[str] = []
            kids = children_from_entry(self.entry)
            if not kids:
                uid = getattr(self.client, "user_id", None)
                if uid:
                    kids = [{"id": str(uid), "name": str(uid)}]
            for index, kid in enumerate(kids):
                if index:
                    await asyncio.sleep(1)
                school = await self._load_child_school(kid["id"], kid["name"])
                if school is None:
                    previous = old_schools.get(kid["id"])
                    if previous is not None:
                        _LOGGER.warning("Wilma keeping last school data for %s", kid["id"])
                        schools[kid["id"]] = previous
                    else:
                        failed.append(kid["id"])
                else:
                    schools[kid["id"]] = school
                # Fetch messages per child
                kid_messages = await self._fetch_child_messages(kid["id"])
                kid_unread = [m for m in kid_messages if m.unread]
                child_msgs[kid["id"]] = ChildMessages(
                    unread=len(kid_unread),
                    count=len(kid_messages),
                    messages=kid_messages[:20],
                    latest=kid_messages[0] if kid_messages else None,
                    unread_source=unread_source,
                )

            if failed and not schools:
                raise UpdateFailed(
                    f"Wilma school fetch failed for all children: {', '.join(failed)}"
                )

            first = next(iter(schools.values()), SchoolData())
            # Combine all children's unread for the global count
            all_unread = []
            all_messages: list[WilmaMessage] = []
            for cm in child_msgs.values():
                all_unread.extend(m for m in cm.messages if m.unread)
                all_messages.extend(cm.messages)
            self._notify_new(all_unread)
            return WilmaData(
                unread=len(all_unread),
                count=sum(cm.count for cm in child_msgs.values()),
                messages=all_messages[:20],
                latest=all_messages[0] if all_messages else None,
                school=first,
                schools=schools,
                child_messages=child_msgs,
                unread_source=unread_source,
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


def _stale_school(school: SchoolData) -> bool:
    """True when probes show a login collision or a dead Wilma session.

    403 on exams/groups/choices/news/list is a permission miss on some
    tenants, not a dead session. Only overview 401/403 counts as auth.
    """
    for probe in school.probes:
        if "LOGIN_COLLISION" in probe:
            return True
        low = probe.lower()
        if "päällekkäinen" in low or "session expired" in low:
            return True
        parts = probe.split()
        if len(parts) >= 2 and parts[0] == "overview" and parts[1] in {"401", "403"}:
            return True
    return False
