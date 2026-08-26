"""Config flow for Wilma."""
from __future__ import annotations

from typing import Any

import voluptuous as vol
from wilhelmina import AuthenticationError, WilmaClient, WilmaError

from homeassistant import config_entries
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .const import (
    CONF_CHILD_ID,
    CONF_CHILD_NAME,
    CONF_CHILDREN,
    CONF_PASSWORD,
    CONF_SCAN_INTERVAL,
    CONF_URL,
    CONF_USERNAME,
    DEFAULT_SCAN_INTERVAL,
    DEFAULT_URL,
    DOMAIN,
)
from .roles import fetch_children

STEP_USER_DATA_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_URL, default=DEFAULT_URL): str,
        vol.Required(CONF_USERNAME): str,
        vol.Required(CONF_PASSWORD): str,
        vol.Optional(CONF_SCAN_INTERVAL, default=DEFAULT_SCAN_INTERVAL): vol.All(
            vol.Coerce(int), vol.Range(min=60, max=3600)
        ),
    }
)


class WilmaConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    VERSION = 3

    def __init__(self) -> None:
        self._data: dict[str, Any] = {}
        self._children: dict[str, str] = {}

    async def async_step_user(self, user_input: dict[str, Any] | None = None):
        errors: dict[str, str] = {}
        if user_input is not None:
            url = user_input[CONF_URL].rstrip("/")
            username = user_input[CONF_USERNAME].strip()
            await self.async_set_unique_id(f"{url}:{username.lower()}")
            self._abort_if_unique_id_configured()
            session = async_get_clientsession(self.hass)
            client = WilmaClient(url, session=session, headless=True)
            try:
                await client.login(username, user_input[CONF_PASSWORD])
                await client.get_messages()
            except AuthenticationError:
                errors["base"] = "invalid_auth"
            except (WilmaError, Exception):
                errors["base"] = "cannot_connect"
            else:
                self._data = {
                    CONF_URL: url,
                    CONF_USERNAME: username,
                    CONF_PASSWORD: user_input[CONF_PASSWORD],
                    CONF_SCAN_INTERVAL: user_input.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL),
                }
                children = await fetch_children(session, url, getattr(client, "user_id", None))
                self._children = {child.child_id: child.name for child in children}
                return await self._async_create()

        return self.async_show_form(step_id="user", data_schema=STEP_USER_DATA_SCHEMA, errors=errors)

    async def _async_create(self):
        kids = [{"id": cid, "name": name} for cid, name in self._children.items()]
        first_id = kids[0]["id"] if kids else ""
        first_name = kids[0]["name"] if kids else self._data[CONF_USERNAME]
        if len(kids) > 1:
            title = f"Wilma ({len(kids)} lasta)"
        else:
            title = f"Wilma ({first_name})"
        return self.async_create_entry(
            title=title,
            data={
                **self._data,
                CONF_CHILD_ID: first_id,
                CONF_CHILD_NAME: first_name,
                CONF_CHILDREN: kids,
            },
        )
