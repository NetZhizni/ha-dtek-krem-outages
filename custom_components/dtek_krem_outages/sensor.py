"""Sensors for DTEK KREM Outages."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
)
from homeassistant.const import EntityCategory, UnitOfTime
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.util import dt as dt_util

from .const import group_name
from .coordinator import DtekConfigEntry, DtekCoordinator
from .entity import DtekEntity
from .schedule import SLOT_MAYBE, format_intervals, intervals, outage_minutes, slot_at

PARALLEL_UPDATES = 0


def _day_value(coordinator: DtekCoordinator, day: date) -> float | None:
    slots = coordinator.data.days.get(day)
    return None if slots is None else outage_minutes(slots) / 60


def _day_attributes(coordinator: DtekCoordinator, day: date) -> dict[str, Any]:
    slots = coordinator.data.days.get(day)
    if slots is None:
        return {"date": day.isoformat(), "published": False}
    tz = coordinator.tz
    outages = intervals({day: slots}, tz)
    possible = intervals({day: slots}, tz, (SLOT_MAYBE,))
    return {
        "date": day.isoformat(),
        "published": True,
        "outages_text": format_intervals(outages, tz),
        "outages": [i.as_dict(tz) for i in outages],
        "possible_text": format_intervals(possible, tz),
        "schedule": slots,
    }


def _today(coordinator: DtekCoordinator, now: datetime) -> date:
    return slot_at(now, coordinator.tz)[0]


def _group_attributes(coordinator: DtekCoordinator, now: datetime) -> dict[str, Any]:
    data = coordinator.data
    return {
        "group_id": data.group,
        "groups_at_address": [group_name(g) for g in data.groups_at_address],
        "manual": coordinator.group_manual,
        "settlement": coordinator.settlement,
        "street": coordinator.street,
        "house": coordinator.house,
    }


def _next_outage_attributes(
    coordinator: DtekCoordinator, now: datetime
) -> dict[str, Any] | None:
    outage = coordinator.data.next_outage(now)
    if outage is None:
        return None
    return {
        "end": outage.end.astimezone(coordinator.tz).isoformat(),
        "duration_minutes": outage.minutes,
    }


def _outage_end_attributes(
    coordinator: DtekCoordinator, now: datetime
) -> dict[str, Any] | None:
    outage = coordinator.data.current_outage(now)
    if outage is None:
        return None
    return {
        "start": outage.start.astimezone(coordinator.tz).isoformat(),
        "duration_minutes": outage.minutes,
    }


@dataclass(frozen=True, kw_only=True)
class DtekSensorDescription(SensorEntityDescription):
    """Describes a DTEK KREM Outages sensor."""

    value_fn: Callable[[DtekCoordinator, datetime], Any]
    attributes_fn: Callable[[DtekCoordinator, datetime], dict[str, Any] | None] = (
        lambda coordinator, now: None
    )


SENSORS: tuple[DtekSensorDescription, ...] = (
    DtekSensorDescription(
        key="group",
        translation_key="group",
        value_fn=lambda c, now: group_name(c.data.group),
        attributes_fn=_group_attributes,
    ),
    DtekSensorDescription(
        key="next_outage",
        translation_key="next_outage",
        device_class=SensorDeviceClass.TIMESTAMP,
        value_fn=lambda c, now: (
            outage.start if (outage := c.data.next_outage(now)) else None
        ),
        attributes_fn=_next_outage_attributes,
    ),
    DtekSensorDescription(
        key="outage_end",
        translation_key="outage_end",
        device_class=SensorDeviceClass.TIMESTAMP,
        value_fn=lambda c, now: (
            outage.end if (outage := c.data.current_outage(now)) else None
        ),
        attributes_fn=_outage_end_attributes,
    ),
    DtekSensorDescription(
        key="outages_today",
        translation_key="outages_today",
        device_class=SensorDeviceClass.DURATION,
        native_unit_of_measurement=UnitOfTime.HOURS,
        suggested_display_precision=1,
        value_fn=lambda c, now: _day_value(c, _today(c, now)),
        attributes_fn=lambda c, now: _day_attributes(c, _today(c, now)),
    ),
    DtekSensorDescription(
        key="outages_tomorrow",
        translation_key="outages_tomorrow",
        device_class=SensorDeviceClass.DURATION,
        native_unit_of_measurement=UnitOfTime.HOURS,
        suggested_display_precision=1,
        value_fn=lambda c, now: _day_value(c, _today(c, now) + timedelta(days=1)),
        attributes_fn=lambda c, now: _day_attributes(
            c, _today(c, now) + timedelta(days=1)
        ),
    ),
    DtekSensorDescription(
        key="schedule_updated",
        translation_key="schedule_updated",
        device_class=SensorDeviceClass.TIMESTAMP,
        value_fn=lambda c, now: c.data.fact_updated_at,
        attributes_fn=lambda c, now: {
            "version": c.data.fact_update,
            "source": c.data.source,
        },
    ),
    DtekSensorDescription(
        key="last_update",
        translation_key="last_update",
        device_class=SensorDeviceClass.TIMESTAMP,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda c, now: c.data.last_success,
        attributes_fn=lambda c, now: {"last_error": c.data.last_error},
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: DtekConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the sensors."""
    coordinator = entry.runtime_data
    async_add_entities(DtekSensor(coordinator, description) for description in SENSORS)


class DtekSensor(DtekEntity, SensorEntity):
    """A sensor computed from the schedule at the current time."""

    entity_description: DtekSensorDescription

    def __init__(
        self, coordinator: DtekCoordinator, description: DtekSensorDescription
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, description.key)
        self.entity_description = description

    @property
    def native_value(self) -> Any:
        """Return the state."""
        return self.entity_description.value_fn(self.coordinator, dt_util.utcnow())

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        """Return extra attributes."""
        return self.entity_description.attributes_fn(self.coordinator, dt_util.utcnow())
