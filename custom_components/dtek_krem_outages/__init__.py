"""The DTEK KREM Outages integration."""

from __future__ import annotations

from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.typing import ConfigType

from .api import async_get_client
from .const import DOMAIN
from .coordinator import DtekConfigEntry, DtekCoordinator, async_remove_store
from .services import async_setup_services

PLATFORMS: list[Platform] = [
    Platform.BINARY_SENSOR,
    Platform.CALENDAR,
    Platform.EVENT,
    Platform.SENSOR,
]

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Register the integration services once."""
    async_setup_services(hass)
    return True


async def async_setup_entry(hass: HomeAssistant, entry: DtekConfigEntry) -> bool:
    """Set up DTEK KREM Outages from a config entry."""
    coordinator = DtekCoordinator(hass, entry, await async_get_client(hass))
    await coordinator.async_load_translations()
    await coordinator.async_config_entry_first_refresh()
    entry.runtime_data = coordinator

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(coordinator.async_enable_event_dispatch())
    return True


async def async_unload_entry(hass: HomeAssistant, entry: DtekConfigEntry) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def async_remove_entry(hass: HomeAssistant, entry: DtekConfigEntry) -> None:
    """Delete the stored schedule when the entry is removed."""
    await async_remove_store(hass, entry.entry_id)
