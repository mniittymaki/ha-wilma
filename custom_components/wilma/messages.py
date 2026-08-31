"""Unread-message detection without Playwright.

Wilhelmina only flags unread messages via a headless Chromium
(`WilmaClient._get_unread_message_ids`), which is not installable in a Home
Assistant container. Without it every message comes back `unread=False`.

The `messages/list` JSON carries the read state, but Wilhelmina's `Message`
model drops the field ("unread is not in the API response"). So we re-read the
same endpoint on the shared session and probe for it, falling back to the HTML
list page. Key spellings vary between Wilma versions, hence the probing.
"""
from __future__ import annotations

import json
import logging
import re
from typing import Any

import aiohttp

_LOGGER = logging.getLogger(__name__)

# Truthy means "not yet read".
UNREAD_KEYS = ("Unread", "unread", "IsUnread", "isUnread", "New", "IsNew", "isNew")
# Truthy means "already read" - inverted.
READ_KEYS = ("IsRead", "isRead", "Read", "read", "Opened", "opened", "Seen")
# Free-text state fields.
STATUS_KEYS = ("Status", "status", "MsgStatus", "State", "state", "Flags", "flags")

UNREAD_WORDS = ("unread", "new", "lukematon", "uusi")
READ_WORDS = ("read", "opened", "luettu", "avattu")

ID_KEYS = ("Id", "id", "MessageId", "messageId", "Mid", "mid")

# Rows on the HTML list page mark unread with a class or a bold subject cell.
ROW_RE = re.compile(r"<tr\b[^>]*>.*?</tr>", re.IGNORECASE | re.DOTALL)
MID_RE = re.compile(r'name="mid"[^>]*value="(\d+)"', re.IGNORECASE)
MSG_LINK_RE = re.compile(r'href="[^"]*?/messages/(\d+)"', re.IGNORECASE)
UNREAD_CLASS_RE = re.compile(
    r'class="[^"]*\b(unread|new|bold|msg-new|bold-link|badge)\b', re.IGNORECASE
)
TD_RE = re.compile(r"<td\b[^>]*>(.*?)</td>", re.IGNORECASE | re.DOTALL)
TD_FULL_RE = re.compile(r"(<td\b[^>]*>)(.*?)</td>", re.IGNORECASE | re.DOTALL)
TAG_RE = re.compile(r"<[^>]+>")
LINK_TEXT_RE = re.compile(r"<a\b[^>]*>(.*?)</a>", re.IGNORECASE | re.DOTALL)


def _msg_id(item: dict) -> int:
    for key in ID_KEYS:
        val = item.get(key)
        if val in (None, ""):
            continue
        try:
            return int(val)
        except (TypeError, ValueError):
            continue
    return 0


def unread_from_item(item: dict) -> bool | None:
    """Return read state for one message dict, or None if undetermined."""
    for key in UNREAD_KEYS:
        if key in item and item[key] is not None:
            return bool(item[key])
    for key in READ_KEYS:
        if key in item and item[key] is not None:
            return not bool(item[key])
    for key in STATUS_KEYS:
        val = item.get(key)
        if isinstance(val, int):
            # Espoo Wilma: Status=1 means unread, None means read
            return val == 1
        if isinstance(val, str) and val.strip():
            low = val.lower()
            if any(word in low for word in UNREAD_WORDS):
                return True
            if any(word in low for word in READ_WORDS):
                return False
    return None


def parse_unread_json(payload: Any) -> tuple[set[int], str]:
    """Pull unread ids out of a messages/list payload."""
    if not isinstance(payload, dict):
        return set(), ""
    items = payload.get("Messages") or payload.get("messages") or []
    if not isinstance(items, list):
        return set(), ""
    unread: set[int] = set()
    matched_key = ""
    for item in items:
        if not isinstance(item, dict):
            continue
        state = unread_from_item(item)
        if state is None:
            continue
        if not matched_key:
            matched_key = next(
                (k for k in (*UNREAD_KEYS, *READ_KEYS, *STATUS_KEYS) if k in item), ""
            )
        mid = _msg_id(item)
        if state and mid:
            unread.add(mid)
    return unread, matched_key


def parse_unread_html(html: str) -> set[int]:
    """Fallback: scrape the rendered message list for unread rows."""
    unread: set[int] = set()
    for row in ROW_RE.findall(html):
        match = MID_RE.search(row) or MSG_LINK_RE.search(row)
        if not match:
            continue
        if UNREAD_CLASS_RE.search(row):
            unread.add(int(match.group(1)))
    return unread


def _strip_tags(html: str) -> str:
    return TAG_RE.sub("", html).strip()


def parse_messages_html(html: str) -> list[dict]:
    """Parse message rows from the HTML list page.

    Real Wilma row structure:
      <td> checkbox (name="mid" value="ID") </td>
      <td> <span class="badge">Uusi</span>  (or empty if read) </td>
      <td> <a href="/.../messages/ID" class="bold-link">Subject</a> </td>
      <td> <a class="profile-link">Sender</a> </td>
      <td> timestamp </td>
    """
    messages: list[dict] = []
    for row in ROW_RE.findall(html):
        mid_m = MID_RE.search(row) or MSG_LINK_RE.search(row)
        if not mid_m:
            continue
        mid = int(mid_m.group(1))
        unread = bool(UNREAD_CLASS_RE.search(row))
        cells = TD_FULL_RE.findall(row)
        subject = sender = timestamp = ""
        for tag, content in cells:
            if MSG_LINK_RE.search(content):
                link_text = LINK_TEXT_RE.findall(content)
                subject = _strip_tags(link_text[0]) if link_text else _strip_tags(content)
                continue
            if "profile-link" in content:
                link_text = LINK_TEXT_RE.findall(content)
                sender = _strip_tags(link_text[0]) if link_text else _strip_tags(content)
                continue
            text = _strip_tags(content)
            if text and ("sortvalue" in tag or not timestamp):
                # Last non-empty cell without a link is the timestamp
                if "mid" not in tag and "badge" not in content:
                    timestamp = text
        if not subject:
            # Fallback: use positional extraction from non-empty cells
            text_cells = [_strip_tags(c) for c in cells if _strip_tags(c)]
            if len(text_cells) >= 3:
                subject, sender, timestamp = text_cells[-3], text_cells[-2], text_cells[-1]
        messages.append({
            "id": mid, "subject": subject, "sender": sender,
            "timestamp": timestamp, "unread": unread,
        })
    return messages


async def fetch_unread_ids(
    session: aiohttp.ClientSession, base_url: str, user_id: str
) -> tuple[set[int], str]:
    """Return (unread ids, diagnostic string) for the given role.

    The diagnostic mirrors the `probes` field on SchoolData: it says which
    endpoint answered and which key carried the state, so a wrong guess is
    visible in the sensor attributes instead of silently reading as "0 unread".
    """
    base = base_url.rstrip("/")
    uid = str(user_id).strip("/")

    url = f"{base}/{uid}/messages/list"
    try:
        async with session.get(url, allow_redirects=True) as resp:
            if resp.status < 400:
                text = await resp.text()
                try:
                    payload = json.loads(text)
                except json.JSONDecodeError:
                    payload = None
                if payload is not None:
                    unread, key = parse_unread_json(payload)
                    if key:
                        return unread, f"json:{key}"
                    sample = ""
                    items = payload.get("Messages") if isinstance(payload, dict) else None
                    if isinstance(items, list) and items and isinstance(items[0], dict):
                        sample = ",".join(list(items[0].keys())[:12])
                    _LOGGER.debug("Wilma unread: no known key in messages/list (%s)", sample)
                    return set(), f"json:no-key[{sample}]"
    except Exception as err:  # noqa: BLE001
        _LOGGER.debug("Wilma unread json probe failed: %s", err)

    url = f"{base}/{uid}/messages"
    try:
        async with session.get(url, allow_redirects=True) as resp:
            if resp.status < 400:
                unread = parse_unread_html(await resp.text())
                if unread:
                    return unread, "html"
                return set(), "html:none"
    except Exception as err:  # noqa: BLE001
        _LOGGER.debug("Wilma unread html probe failed: %s", err)

    return set(), "unavailable"


async def fetch_messages_html(
    session: aiohttp.ClientSession, base_url: str, user_id: str
) -> list[dict]:
    """Fetch messages by scraping the HTML list page.

    Used as fallback when the JSON API returns malformed responses.
    """
    base = base_url.rstrip("/")
    uid = str(user_id).strip("/")
    url = f"{base}/{uid}/messages"
    try:
        async with session.get(url, allow_redirects=True) as resp:
            if resp.status < 400:
                return parse_messages_html(await resp.text())
    except Exception as err:  # noqa: BLE001
        _LOGGER.debug("Wilma HTML message fetch failed: %s", err)
    return []
