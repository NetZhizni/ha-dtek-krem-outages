"""Repairs for DTEK KREM Outages.

The coordinator raises an issue when DTEK lists other groups for the house
without the main group of the entry, and keeps it as long as that lasts. Its
fix flow makes one of the groups DTEK lists the main group.
"""

from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant.components.repairs import RepairsFlow
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResult

from .config_flow import group_select
from .const import CONF_GROUP, DOMAIN
from .coordinator import DtekConfigEntry


class GroupNotListedFlow(RepairsFlow):
    """Change the main group to one of the groups DTEK lists for the house."""

    def __init__(self, entry_id: str) -> None:
        """Initialize the flow for an entry."""
        self._entry_id = entry_id

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Start with the choice of the group."""
        return await self.async_step_change()

    async def async_step_change(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Choose the new main group; the groups DTEK lists now are offered."""
        entry: DtekConfigEntry | None = self.hass.config_entries.async_get_entry(
            self._entry_id
        )
        if (
            entry is None
            or entry.domain != DOMAIN
            or entry.state is not ConfigEntryState.LOADED
        ):
            return self.async_abort(reason="entry_not_loaded")
        coordinator = entry.runtime_data
        if not (choices := coordinator.group_suggestions()):
            return self.async_abort(reason="group_listed")
        if user_input is not None and user_input.get(CONF_GROUP) in choices:
            await coordinator.async_change_group(user_input[CONF_GROUP])
            return self.async_create_entry(data={})
        return self.async_show_form(
            step_id="change",
            data_schema=vol.Schema(
                {vol.Required(CONF_GROUP, default=choices[0]): group_select(choices)}
            ),
            description_placeholders=coordinator.group_issue_placeholders(),
        )


async def async_create_fix_flow(
    hass: HomeAssistant,
    issue_id: str,
    data: dict[str, str | int | float | None] | None,
) -> RepairsFlow:
    """Return the fix flow of an issue of the integration."""
    return GroupNotListedFlow(str((data or {}).get("entry_id") or ""))
