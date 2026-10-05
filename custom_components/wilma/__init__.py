"""Wilma integration."""
from __future__ import annotations

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, ServiceCall, ServiceResponse, SupportsResponse
from homeassistant.exceptions import (
    ConfigEntryAuthFailed,
    ConfigEntryNotReady,
    HomeAssistantError,
    ServiceValidationError,
)
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er

from .const import DOMAIN
from .coordinator import WilmaCoordinator
from .messages import MessageNotFound

PLATFORMS = [Platform.SENSOR, Platform.CALENDAR]

SERVICE_GET_MESSAGE = "get_message"
SERVICE_PIN_MESSAGE = "pin_message"
SERVICE_UNPIN_MESSAGE = "unpin_message"
GET_MESSAGE_SCHEMA = vol.Schema(
    {
        vol.Optional("entity_id"): cv.entity_id,
        vol.Optional("device_id"): cv.string,
        vol.Required("message_id"): cv.positive_int,
    }
)


def _child_from_call(hass: HomeAssistant, call: ServiceCall) -> tuple[WilmaCoordinator, str]:
    """The coordinator and child id behind any Wilma entity or device of that child."""
    device_id = call.data.get("device_id")
    if not device_id and (entity_id := call.data.get("entity_id")):
        entity = er.async_get(hass).async_get(entity_id)
        device_id = entity.device_id if entity else None
    device = dr.async_get(hass).async_get(device_id) if device_id else None
    identifier = next((ident[1] for ident in device.identifiers if ident[0] == DOMAIN), "") if device else ""
    if not identifier:
        raise ServiceValidationError("Give entity_id or device_id of a Wilma child")
    entry_id, _, child_id = identifier.partition(":")
    coordinator = hass.data.get(DOMAIN, {}).get(entry_id)
    if not isinstance(coordinator, WilmaCoordinator):
        raise ServiceValidationError("The Wilma entry of that child is not loaded")
    return coordinator, child_id


def _register_services(hass: HomeAssistant) -> None:
    if hass.services.has_service(DOMAIN, SERVICE_GET_MESSAGE):
        return

    async def get_message(call: ServiceCall) -> ServiceResponse:
        coordinator, child_id = _child_from_call(hass, call)
        try:
            return await coordinator.async_get_message(child_id, call.data["message_id"])
        except MessageNotFound as err:
            raise ServiceValidationError(f"Wilma message {call.data['message_id']} not available: {err}") from err
        except Exception as err:  # noqa: BLE001
            raise HomeAssistantError(f"Wilma message fetch failed: {err}") from err

    hass.services.async_register(
        DOMAIN,
        SERVICE_GET_MESSAGE,
        get_message,
        schema=GET_MESSAGE_SCHEMA,
        supports_response=SupportsResponse.ONLY,
    )

    async def pin_message(call: ServiceCall) -> None:
        coordinator, child_id = _child_from_call(hass, call)
        try:
            await coordinator.async_pin_message(child_id, call.data["message_id"])
        except ValueError as err:
            raise ServiceValidationError(f"Cannot pin: {err}") from err

    async def unpin_message(call: ServiceCall) -> None:
        coordinator, child_id = _child_from_call(hass, call)
        await coordinator.async_unpin_message(child_id, call.data["message_id"])

    hass.services.async_register(DOMAIN, SERVICE_PIN_MESSAGE, pin_message, schema=GET_MESSAGE_SCHEMA)
    hass.services.async_register(DOMAIN, SERVICE_UNPIN_MESSAGE, unpin_message, schema=GET_MESSAGE_SCHEMA)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    coordinator = WilmaCoordinator(hass, entry)
    await coordinator.async_setup()
    try:
        await coordinator.async_config_entry_first_refresh()
    except ConfigEntryAuthFailed:
        await coordinator.async_shutdown()
        raise
    except Exception as err:
        await coordinator.async_shutdown()
        raise ConfigEntryNotReady(str(err)) from err

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinator
    _register_services(hass)
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    coordinator: WilmaCoordinator | None = hass.data[DOMAIN].pop(entry.entry_id, None)
    if coordinator:
        await coordinator.async_shutdown()
    if not any(isinstance(item, WilmaCoordinator) for item in hass.data[DOMAIN].values()):
        for service in (SERVICE_GET_MESSAGE, SERVICE_PIN_MESSAGE, SERVICE_UNPIN_MESSAGE):
            hass.services.async_remove(DOMAIN, service)
    return unload_ok
