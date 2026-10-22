"""Calendars for DTEK KREM Outages."""

from __future__ import annotations

from collections.abc import Callable
from datetime import date, datetime
from typing import Any

from homeassistant.components.calendar import CalendarEntity, CalendarEvent
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.util import dt as dt_util

from .const import (
    CALENDAR_TEXT,
    OUTAGE_KIND_STABILIZATION,
    POSSIBLE_DAYS_AHEAD,
    group_name,
)
from .coordinator import DtekConfigEntry, DtekCoordinator
from .entity import DtekEntity
from .schedule import SLOT_MAYBE, SLOT_OFF, Interval, intervals, possible_days, slot_at

PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant,
    entry: DtekConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the calendars."""
    coordinator = entry.runtime_data
    async_add_entities([OutageCalendar(coordinator), OtherGroupsCalendar(coordinator)])


class _DtekCalendar(DtekEntity, CalendarEntity):
    """A calendar built from the schedule of the entry."""

    def _text(self) -> dict[str, str]:
        return CALENDAR_TEXT.get(self.coordinator.language, CALENDAR_TEXT["en"])

    def _label(self, groups: list[str]) -> str:
        """Return ``Черга 3.1`` or ``Черги 3.1, 5.1`` in the calendar language."""
        text = self._text()
        names = ", ".join(group_name(g) or g for g in groups)
        return f"{text['group' if len(groups) == 1 else 'groups']} {names}"

    def _events(self) -> list[CalendarEvent]:
        raise NotImplementedError

    def _schedule_events(
        self,
        days: dict[date, str],
        preset: dict[int, str],
        label: str,
        uid: str,
        *,
        prefix: str = "",
        describe: Callable[[Interval], str] | None = None,
    ) -> list[CalendarEvent]:
        """Return the outages and possible outages of a schedule.

        Days without an actual schedule show the weekly schedule of possible
        outages when that option is on and DTEK shows that schedule itself.
        ``describe`` gives the description of an actual outage instead of
        ``label``.
        """
        coordinator = self.coordinator
        tz = coordinator.tz
        text = self._text()
        events = [
            CalendarEvent(
                start=item.start.astimezone(tz),
                end=item.end.astimezone(tz),
                summary=prefix
                + (text["outage"] if item.kind != SLOT_MAYBE else text["possible"]),
                description=describe(item) if describe else label,
                uid=f"{uid}-{item.start.isoformat()}",
            )
            for item in intervals(days, tz, (SLOT_OFF, SLOT_MAYBE))
        ]
        # ``showTablePlan: false``: the DTEK page hides the weekly schedule.
        if (
            coordinator.show_possible
            and preset
            and coordinator.data.publication.weekly is not False
        ):
            today, _ = slot_at(dt_util.utcnow(), tz)
            weekly = possible_days(preset, today, POSSIBLE_DAYS_AHEAD, days)
            events.extend(
                CalendarEvent(
                    start=item.start.astimezone(tz),
                    end=item.end.astimezone(tz),
                    summary=prefix + text["possible"],
                    description=f"{label}\n{text['weekly']}",
                    uid=f"{uid}-possible-{item.start.isoformat()}",
                )
                for item in intervals(weekly, tz, (SLOT_MAYBE,))
            )
        return events

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return how fresh the schedule is."""
        return self.coordinator.data.freshness()

    @property
    def event(self) -> CalendarEvent | None:
        """Return the event in progress, else the next one."""
        now = dt_util.utcnow()
        upcoming = [e for e in self._events() if e.end_datetime_local > now]
        return upcoming[0] if upcoming else None

    async def async_get_events(
        self, hass: HomeAssistant, start_date: datetime, end_date: datetime
    ) -> list[CalendarEvent]:
        """Return the events overlapping the requested range."""
        return [
            event
            for event in self._events()
            if event.start_datetime_local < end_date
            and event.end_datetime_local > start_date
        ]


class OutageCalendar(_DtekCalendar):
    """Scheduled outages, possible outages and works reported for the address.

    The schedule is the one the other entities show: the main group, or all
    groups of the address when they are combined, each event then naming the
    groups off during it. Stabilization outages reported for the address are
    left out: the schedule already shows them.
    """

    def __init__(self, coordinator: DtekCoordinator) -> None:
        """Initialize the calendar."""
        super().__init__(coordinator, "outages")

    def _events(self) -> list[CalendarEvent]:
        coordinator = self.coordinator
        data = coordinator.data
        entry_id = coordinator.config_entry.entry_id
        if data.combined:
            label = self._label([data.group, *data.extra_groups])

            def describe(item: Interval) -> str:
                groups = coordinator.groups_in(item)
                return self._label(groups) if groups else label

            events = self._schedule_events(
                data.days, data.preset, label, entry_id, describe=describe
            )
        else:
            label = self._label([data.group])
            events = self._schedule_events(data.days, data.preset, label, entry_id)
        outage = data.address_outage
        if (
            outage is not None
            and outage.kind != OUTAGE_KIND_STABILIZATION
            and outage.start is not None
            and outage.end is not None
            and outage.end > outage.start
        ):
            events.append(
                CalendarEvent(
                    start=outage.start,
                    end=outage.end,
                    summary=outage.reason,
                    description=label,
                    location=(
                        f"{coordinator.settlement}, {coordinator.street}, "
                        f"{coordinator.house}"
                        if coordinator.has_address
                        else None
                    ),
                    uid=f"{entry_id}-address-{outage.start.isoformat()}",
                )
            )
        return sorted(events, key=lambda e: e.start_datetime_local)


class OtherGroupsCalendar(_DtekCalendar):
    """Outages of the other groups of the address, each named with its group.

    Empty while DTEK lists one group for the house (or, for an entry without
    an address, while no other group is chosen in the options).
    """

    def __init__(self, coordinator: DtekCoordinator) -> None:
        """Initialize the calendar."""
        super().__init__(coordinator, "other_groups")

    def _events(self) -> list[CalendarEvent]:
        data = self.coordinator.data
        text = self._text()
        entry_id = self.coordinator.config_entry.entry_id
        events: list[CalendarEvent] = []
        for group in data.extra_groups:
            label = f"{text['group']} {group_name(group)}"
            events.extend(
                self._schedule_events(
                    data.group_days.get(group, {}),
                    data.group_presets.get(group, {}),
                    label,
                    f"{entry_id}-{group}",
                    prefix=f"{label}: ",
                )
            )
        return sorted(events, key=lambda e: e.start_datetime_local)
