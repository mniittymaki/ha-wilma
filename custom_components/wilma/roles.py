"""Discover Wilma guardian roles / children."""
from __future__ import annotations

from dataclasses import dataclass
import json
import re
from typing import Any

import aiohttp

ROLE_RE = re.compile(r"/(!?\d{5,12})")
NAME_RE = re.compile(r">\s*([^<]{2,80})\s*<")


@dataclass
class WilmaChild:
    child_id: str
    name: str


def _norm_id(raw: str) -> str:
    raw = str(raw).strip().strip("/")
    if not raw:
        return ""
    if raw.startswith("!"):
        return raw
    if raw.isdigit():
        return f"!{raw}"
    return raw


def _name_from(item: dict) -> str:
    for key in ("Name", "name", "Caption", "caption", "StudentName", "FullName", "Title"):
        val = item.get(key)
        if val:
            return str(val).strip()
    return ""


def _id_from(item: dict) -> str:
    for key in ("Id", "id", "PrimusId", "UserId", "userId", "Slug", "FormKey"):
        val = item.get(key)
        if val not in (None, ""):
            return _norm_id(str(val))
    return ""


def parse_roles(payload: Any) -> list[WilmaChild]:
    found: dict[str, str] = {}
    if isinstance(payload, dict):
        buckets = (
            payload.get("Roles")
            or payload.get("roles")
            or payload.get("Students")
            or payload.get("students")
            or payload.get("Records")
            or [payload]
        )
        if isinstance(buckets, dict):
            buckets = list(buckets.values())
        if isinstance(buckets, list):
            for item in buckets:
                if not isinstance(item, dict):
                    continue
                cid = _id_from(item)
                if not cid:
                    continue
                found[cid] = _name_from(item) or found.get(cid) or cid
    elif isinstance(payload, str):
        for match in re.finditer(r'href="(/!\d+)"[^>]*>([^<]{2,80})', payload):
            found[_norm_id(match.group(1))] = match.group(2).strip()
        if not found:
            for match in ROLE_RE.finditer(payload):
                cid = _norm_id(match.group(1))
                found.setdefault(cid, cid)
    return [WilmaChild(child_id=cid, name=name) for cid, name in found.items()]


async def fetch_children(
    session: aiohttp.ClientSession, base_url: str, user_id: str | None
) -> list[WilmaChild]:
    base = base_url.rstrip("/")
    uid = _norm_id(user_id or "")
    paths = []
    if uid:
        paths.extend([f"{base}/{uid}/roles", f"{base}/{uid}"])
    paths.append(f"{base}/")
    children: list[WilmaChild] = []
    for url in paths:
        try:
            async with session.get(url, allow_redirects=True) as resp:
                if resp.status >= 400:
                    continue
                text = await resp.text()
                ctype = resp.headers.get("Content-Type", "")
                payload: Any = text
                if "json" in ctype or text[:1] in "{[":
                    try:
                        payload = json.loads(text)
                    except json.JSONDecodeError:
                        payload = text
                parsed = parse_roles(payload)
                if parsed:
                    children = parsed
                    break
        except Exception:  # noqa: BLE001
            continue
    if uid and not any(child.child_id == uid for child in children):
        children.insert(0, WilmaChild(child_id=uid, name=uid))
    return children


async def switch_child(session: aiohttp.ClientSession, base_url: str, child_id: str) -> None:
    cid = _norm_id(child_id)
    if not cid:
        return
    url = f"{base_url.rstrip('/')}/{cid}"
    async with session.get(url, allow_redirects=True) as resp:
        await resp.read()
