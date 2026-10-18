"""Event entity for DTEK KREM Outages."""

from __future__ import annotations

from typing import Any

from homeassistant.components.event import EventEntity
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .const import EVENT_TYPES, signal_event
from .coordinator import DtekConfigEntry, DtekCoordinator
from .entity import DtekEntity

PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant,
    entry: DtekConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the event entity."""
    async_add_entities([OutageEvent(entry.runtime_data)])


class OutageEvent(DtekEntity, EventEntity):
    """Fires for schedule changes, warnings, outage edges and address outages."""

    _unrecorded_attributes = frozenset(
        {"outages", "previous_outages", "possible", "schedule"}
    )

    def __init__(self, coordinator: DtekCoordinator) -> None:
        """Initialize the event entity."""
        super().__init__(coordinator, "events")
        self._attr_event_types = list(EVENT_TYPES)

    async def async_added_to_hass(self) -> None:
        """Listen for the events of this entry."""
        await super().async_added_to_hass()
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass,
                signal_event(self.coordinator.config_entry.entry_id),
                self._async_handle_event,
            )
        )

    @callback
    def _async_handle_event(self, event_type: str, payload: dict[str, Any]) -> None:
        self._trigger_event(
            event_type, {key: value for key, value in payload.items() if key != "type"}
        )
        self.async_write_ha_state()
