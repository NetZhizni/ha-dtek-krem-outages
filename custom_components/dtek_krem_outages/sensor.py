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

from .const import (
    ADDRESS_STATUS_NONE,
    ADDRESS_STATUSES,
    CONNECTION_STATES,
    OUTAGE_KIND_OTHER,
    group_name,
)
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
        "external_operator": data.external_operator,
    }


def _address_status(coordinator: DtekCoordinator, now: datetime) -> str:
    outage = coordinator.data.address_outage
    if outage is None:
        return ADDRESS_STATUS_NONE
    return outage.kind if outage.kind in ADDRESS_STATUSES else OUTAGE_KIND_OTHER


def _address_attributes(coordinator: DtekCoordinator, now: datetime) -> dict[str, Any]:
    outage = coordinator.data.address_outage
    data = outage.as_dict() if outage else {}
    return {
        "reason": data.get("reason"),
        "start": data.get("start"),
        "end": data.get("end"),
        "active": outage is not None and outage.is_active(now),
        "external_operator": coordinator.data.external_operator,
    }


def _connection_attributes(
    coordinator: DtekCoordinator, now: datetime
) -> dict[str, Any]:
    data = coordinator.data
    publication = data.publication
    interval = coordinator.update_interval
    return {
        "last_success": _isoformat(data.last_success),
        "last_dtek_success": _isoformat(data.last_dtek_success),
        "consecutive_failures": data.consecutive_failures,
        "update_interval_minutes": round(interval.total_seconds() / 60, 1)
        if interval
        else None,
        "blocked": data.blocked,
        "last_error": data.last_error,
        # None until DTEK has answered once (never for an entry by group only).
        "daily_schedule_shown": None
        if publication.daily is None and publication.schedule is None
        else not publication.daily_hidden,
        "weekly_schedule_shown": publication.weekly,
    }


def _isoformat(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None


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
    # Computed from the schedule: add ``data_status`` and ``last_verified_at``.
    freshness: bool = False
    # Needs the address; unavailable while DTEK can't be reached.
    address: bool = False


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
        freshness=True,
    ),
    DtekSensorDescription(
        key="outage_end",
        translation_key="outage_end",
        device_class=SensorDeviceClass.TIMESTAMP,
        value_fn=lambda c, now: (
            outage.end if (outage := c.data.current_outage(now)) else None
        ),
        attributes_fn=_outage_end_attributes,
        freshness=True,
    ),
    DtekSensorDescription(
        key="outages_today",
        translation_key="outages_today",
        device_class=SensorDeviceClass.DURATION,
        native_unit_of_measurement=UnitOfTime.HOURS,
        suggested_display_precision=1,
        value_fn=lambda c, now: _day_value(c, _today(c, now)),
        attributes_fn=lambda c, now: _day_attributes(c, _today(c, now)),
        freshness=True,
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
        freshness=True,
    ),
    DtekSensorDescription(
        key="address_status",
        translation_key="address_status",
        device_class=SensorDeviceClass.ENUM,
        options=list(ADDRESS_STATUSES),
        value_fn=_address_status,
        attributes_fn=_address_attributes,
        address=True,
    ),
    DtekSensorDescription(
        key="restoration",
        translation_key="restoration",
        device_class=SensorDeviceClass.TIMESTAMP,
        value_fn=lambda c, now: (
            outage.end if (outage := c.data.address_outage) else None
        ),
        attributes_fn=lambda c, now: {
            "reason": outage.reason if (outage := c.data.address_outage) else None,
        },
        address=True,
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
    DtekSensorDescription(
        key="connection",
        translation_key="connection",
        device_class=SensorDeviceClass.ENUM,
        options=list(CONNECTION_STATES),
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda c, now: c.data.connection,
        attributes_fn=_connection_attributes,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: DtekConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the sensors."""
    coordinator = entry.runtime_data
    async_add_entities(
        DtekSensor(coordinator, description)
        for description in SENSORS
        if coordinator.has_address or not description.address
    )


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
    def available(self) -> bool:
        """Return False for address data that is not current."""
        return super().available and (
            not self.entity_description.address or self.coordinator.data.address_ok
        )

    @property
    def native_value(self) -> Any:
        """Return the state."""
        return self.entity_description.value_fn(self.coordinator, dt_util.utcnow())

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        """Return extra attributes."""
        description = self.entity_description
        attributes = description.attributes_fn(self.coordinator, dt_util.utcnow())
        if not description.freshness:
            return attributes
        return {**(attributes or {}), **self.coordinator.data.freshness()}
