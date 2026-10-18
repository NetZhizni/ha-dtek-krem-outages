"""Binary sensors for DTEK KREM Outages."""

from __future__ import annotations

from typing import Any

from homeassistant.components.binary_sensor import BinarySensorEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.util import dt as dt_util

from .coordinator import DtekConfigEntry, DtekCoordinator
from .entity import DtekEntity

PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant,
    entry: DtekConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the binary sensors."""
    coordinator = entry.runtime_data
    async_add_entities(
        [
            ScheduledOutageBinarySensor(coordinator),
            AddressOutageBinarySensor(coordinator),
        ]
    )


class ScheduledOutageBinarySensor(DtekEntity, BinarySensorEntity):
    """On while the schedule of the group has an outage.

    The coordinator wakes up at every outage edge, so the state switches at
    the exact time and not only on the next update.
    """

    def __init__(self, coordinator: DtekCoordinator) -> None:
        """Initialize the binary sensor."""
        super().__init__(coordinator, "scheduled_outage")

    @property
    def is_on(self) -> bool:
        """Return True during a scheduled outage."""
        return self.coordinator.data.current_outage(dt_util.utcnow()) is not None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return the current and the next outage."""
        now = dt_util.utcnow()
        tz = self.coordinator.tz
        current = self.coordinator.data.current_outage(now)
        upcoming = self.coordinator.data.next_outage(now)
        current_data = current.as_dict(tz) if current else {}
        upcoming_data = upcoming.as_dict(tz) if upcoming else {}
        return {
            "start": current_data.get("start"),
            "end": current_data.get("end"),
            "next_start": upcoming_data.get("start"),
            "next_end": upcoming_data.get("end"),
        }


class AddressOutageBinarySensor(DtekEntity, BinarySensorEntity):
    """On while DTEK reports an outage for the address.

    This covers emergency and planned works too, which the group schedule
    doesn't show. Unavailable when the last request to DTEK failed.
    """

    def __init__(self, coordinator: DtekCoordinator) -> None:
        """Initialize the binary sensor."""
        super().__init__(coordinator, "address_outage")

    @property
    def available(self) -> bool:
        """Return False when the address data is not current."""
        return super().available and self.coordinator.data.address_ok

    @property
    def is_on(self) -> bool:
        """Return True while the reported outage lasts."""
        outage = self.coordinator.data.address_outage
        return outage is not None and outage.is_active(dt_util.utcnow())

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return the reported outage."""
        outage = self.coordinator.data.address_outage
        if outage is None:
            return {"reason": None, "kind": None, "start": None, "end": None}
        data = outage.as_dict()
        return {key: data[key] for key in ("reason", "kind", "start", "end")}
