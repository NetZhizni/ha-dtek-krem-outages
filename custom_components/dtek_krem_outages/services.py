"""Services for DTEK KREM Outages."""

from __future__ import annotations

import asyncio

import voluptuous as vol

from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import (
    HomeAssistant,
    ServiceCall,
    ServiceResponse,
    SupportsResponse,
    callback,
)
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers import config_validation as cv

from .const import ATTR_CONFIG_ENTRY_ID, DOMAIN
from .coordinator import DtekCoordinator

SERVICE_REFRESH = "refresh"
SERVICE_GET_SCHEDULE = "get_schedule"

SERVICE_SCHEMA = vol.Schema({vol.Optional(ATTR_CONFIG_ENTRY_ID): cv.string})


@callback
def _get_coordinators(hass: HomeAssistant, call: ServiceCall) -> list[DtekCoordinator]:
    """Return the coordinator of the given entry, or of every loaded entry."""
    if entry_id := call.data.get(ATTR_CONFIG_ENTRY_ID):
        entry = hass.config_entries.async_get_entry(entry_id)
        if entry is None or entry.domain != DOMAIN:
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="entry_not_found",
                translation_placeholders={"entry_id": entry_id},
            )
        if entry.state is not ConfigEntryState.LOADED:
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="entry_not_loaded",
                translation_placeholders={"entry_id": entry_id},
            )
        return [entry.runtime_data]

    coordinators = [
        entry.runtime_data for entry in hass.config_entries.async_loaded_entries(DOMAIN)
    ]
    if not coordinators:
        raise ServiceValidationError(
            translation_domain=DOMAIN, translation_key="no_loaded_entries"
        )
    return coordinators


async def _async_refresh(call: ServiceCall) -> None:
    coordinators = _get_coordinators(call.hass, call)
    await asyncio.gather(*(c.async_refresh() for c in coordinators))
    if failed := [
        c.config_entry.title
        for c in coordinators
        if not c.last_update_success or not c.data.fetch_ok
    ]:
        raise HomeAssistantError(
            translation_domain=DOMAIN,
            translation_key="refresh_failed",
            translation_placeholders={"entries": ", ".join(failed)},
        )


async def _async_get_schedule(call: ServiceCall) -> ServiceResponse:
    coordinators = _get_coordinators(call.hass, call)
    return {"entries": [c.schedule_dict() for c in coordinators]}


@callback
def async_setup_services(hass: HomeAssistant) -> None:
    """Register the integration services."""
    hass.services.async_register(
        DOMAIN, SERVICE_REFRESH, _async_refresh, schema=SERVICE_SCHEMA
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_GET_SCHEDULE,
        _async_get_schedule,
        schema=SERVICE_SCHEMA,
        supports_response=SupportsResponse.ONLY,
    )
