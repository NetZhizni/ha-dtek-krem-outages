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
    GROUPS_STATUS_MAIN,
    GROUPS_STATUS_MAIN_ALL,
    GROUPS_STATUS_MAIN_SOME,
    GROUPS_STATUS_NONE,
    GROUPS_STATUS_OTHERS_ALL,
    GROUPS_STATUS_OTHERS_SOME,
    GROUPS_STATUSES,
    OUTAGE_KIND_OTHER,
    group_name,
)
from .coordinator import DtekConfigEntry, DtekCoordinator
from .entity import DtekEntity
from .schedule import (
    SLOT_MAYBE,
    SLOT_OFF,
    SLOTS_PER_DAY,
    format_intervals,
    intervals,
    outage_minutes,
    slot_at,
)

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
        # Each followed group alone, the main one first; None without a schedule.
        "groups": {
            group_name(group): format_intervals(intervals({day: days[day]}, tz), tz)
            if day in days
            else None
            for group, days in coordinator.data.group_days.items()
        },
    }


def _today(coordinator: DtekCoordinator, now: datetime) -> date:
    return slot_at(now, coordinator.tz)[0]


def _group_attributes(coordinator: DtekCoordinator, now: datetime) -> dict[str, Any]:
    data = coordinator.data
    return {
        "group_id": data.group,
        "groups_at_address": [group_name(g) for g in data.groups_at_address],
        "extra_groups": [group_name(g) for g in data.extra_groups],
        # The mode in effect, like ``get_schedule``: ``main`` without others.
        "groups_mode": data.groups_mode,
        "manual": coordinator.group_manual,
        "settlement": coordinator.settlement,
        "street": coordinator.street,
        "house": coordinator.house,
        "external_operator": data.external_operator,
    }


def _status(main_off: bool, others_off: int, extras: int) -> str:
    """Return the groups status for the main group and some other groups off."""
    all_others = extras > 0 and others_off >= extras
    if main_off:
        if all_others:
            return GROUPS_STATUS_MAIN_ALL
        return GROUPS_STATUS_MAIN_SOME if others_off else GROUPS_STATUS_MAIN
    if all_others:
        return GROUPS_STATUS_OTHERS_ALL
    return GROUPS_STATUS_OTHERS_SOME if others_off else GROUPS_STATUS_NONE


def _groups_status(coordinator: DtekCoordinator, now: datetime) -> str:
    """Return which of the followed groups are off now, by their own schedule."""
    data = coordinator.data
    off = coordinator.groups_off(now)
    return _status(
        data.group in off,
        len([g for g in off if g != data.group]),
        len(data.extra_groups),
    )


def _groups_status_day(
    coordinator: DtekCoordinator, day: date
) -> list[dict[str, Any]] | None:
    """Return the whole day as runs of one status with the same groups off.

    None while no followed group has a schedule for the day. A group without
    one counts as power on.
    """
    data = coordinator.data
    schedules = {g: days[day] for g, days in data.group_days.items() if day in days}
    if not schedules:
        return None
    # Each distinct status and set of groups off gets a letter, so the runs
    # come from ``intervals`` like the outages do, right across a DST change.
    runs: list[tuple[str, tuple[str, ...]]] = []
    letters = []
    for index in range(SLOTS_PER_DAY):
        off = tuple(g for g, slots in schedules.items() if slots[index] == SLOT_OFF)
        run = (
            _status(
                data.group in off,
                len([g for g in off if g != data.group]),
                len(data.extra_groups),
            ),
            off,
        )
        if run not in runs:
            runs.append(run)
        letters.append(chr(ord("a") + runs.index(run)))
    tz = coordinator.tz
    kinds = {chr(ord("a") + i) for i in range(len(runs))}
    result = []
    for item in intervals({day: "".join(letters)}, tz, kinds):
        status, off = runs[ord(item.kind) - ord("a")]
        result.append(
            {
                **item.as_dict(tz),
                "state": status,
                "level": GROUPS_STATUSES.index(status),
                "groups": [group_name(g) for g in off],
            }
        )
    return result


def _groups_status_attributes(
    coordinator: DtekCoordinator, now: datetime
) -> dict[str, Any]:
    data = coordinator.data
    today = _today(coordinator, now)
    return {
        "groups_off": [group_name(g) for g in coordinator.groups_off(now)],
        "main_group": group_name(data.group),
        "extra_groups": [group_name(g) for g in data.extra_groups],
        "level": GROUPS_STATUSES.index(_groups_status(coordinator, now)),
        "today": _groups_status_day(coordinator, today),
        "tomorrow": _groups_status_day(coordinator, today + timedelta(days=1)),
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
        key="groups_status",
        translation_key="groups_status",
        device_class=SensorDeviceClass.ENUM,
        options=list(GROUPS_STATUSES),
        value_fn=_groups_status,
        attributes_fn=_groups_status_attributes,
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
    # The whole-day timelines of the groups status change with the schedule
    # and are there for charts, not for history.
    _unrecorded_attributes = frozenset({"today", "tomorrow"})

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
