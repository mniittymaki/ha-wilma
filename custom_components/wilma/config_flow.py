"""Config flow for Wilma."""
from __future__ import annotations

from typing import Any

import aiohttp
import voluptuous as vol
from wilhelmina import AuthenticationError, WilmaClient, WilmaError

from homeassistant import config_entries
from homeassistant.exceptions import HomeAssistantError

from .const import (
    BROWSER_HEADERS,
    CONF_PASSWORD,
    CONF_SCAN_INTERVAL,
    CONF_URL,
    CONF_USERNAME,
    DEFAULT_SCAN_INTERVAL,
    DEFAULT_URL,
    DOMAIN,
)

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


async def _validate(url: str, username: str, password: str) -> None:
    session = aiohttp.ClientSession(headers=BROWSER_HEADERS)
    client = WilmaClient(url, session=session, headless=True)
    try:
        await client.login(username, password)
        await client.get_messages()
    except AuthenticationError as err:
        raise InvalidAuth from err
    except WilmaError as err:
        raise CannotConnect from err
    except Exception as err:
        raise CannotConnect from err
    finally:
        await session.close()


class WilmaConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    VERSION = 4

    async def async_step_user(self, user_input: dict[str, Any] | None = None):
        errors: dict[str, str] = {}
        if user_input is not None:
            url = user_input[CONF_URL].strip().rstrip("/")
            username = user_input[CONF_USERNAME].strip()
            await self.async_set_unique_id(f"{url}:{username.lower()}")
            self._abort_if_unique_id_configured()
            try:
                await _validate(url, username, user_input[CONF_PASSWORD])
            except InvalidAuth:
                errors["base"] = "invalid_auth"
            except CannotConnect:
                errors["base"] = "cannot_connect"
            else:
                return self.async_create_entry(
                    title=f"Wilma ({username})",
                    data={
                        CONF_URL: url,
                        CONF_USERNAME: username,
                        CONF_PASSWORD: user_input[CONF_PASSWORD],
                        CONF_SCAN_INTERVAL: user_input.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL),
                    },
                )
        return self.async_show_form(step_id="user", data_schema=STEP_USER_DATA_SCHEMA, errors=errors)


class InvalidAuth(HomeAssistantError):
    """Bad credentials."""


class CannotConnect(HomeAssistantError):
    """Cannot reach Wilma."""
