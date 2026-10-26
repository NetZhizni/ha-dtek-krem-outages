"""Diagnostics for DTEK KREM Outages.

The street and house number are redacted; the settlement and group stay,
since the schedule can't be understood without them.
"""

from __future__ import annotations

from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.core import HomeAssistant

from .const import CONF_HOUSE, CONF_STREET
from .coordinator import DtekConfigEntry

TO_REDACT = {CONF_STREET, CONF_HOUSE, "street", "house", "entry_title", "title"}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: DtekConfigEntry
) -> dict[str, Any]:
    """Return diagnostics for a config entry."""
    coordinator = entry.runtime_data
    return {
        "entry": async_redact_data(
            {
                "title": entry.title,
                "data": dict(entry.data),
                "options": dict(entry.options),
            },
            TO_REDACT,
        ),
        "coordinator": {
            "last_update_success": coordinator.last_update_success,
            "last_exception": repr(coordinator.last_exception)
            if coordinator.last_exception
            else None,
            "update_interval_seconds": coordinator.update_interval.total_seconds()
            if coordinator.update_interval
            else None,
        },
        "state": async_redact_data(coordinator.schedule_dict(), TO_REDACT)
        if coordinator.data
        else None,
    }
