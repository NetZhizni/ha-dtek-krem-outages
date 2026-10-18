"""Calendar for DTEK KREM Outages."""

from __future__ import annotations

from datetime import datetime

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
from .schedule import SLOT_MAYBE, SLOT_OFF, intervals, possible_days, slot_at

PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant,
    entry: DtekConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the calendar."""
    async_add_entities([OutageCalendar(entry.runtime_data)])


class OutageCalendar(DtekEntity, CalendarEntity):
    """Scheduled outages, possible outages and works reported for the address.

    Days without an actual schedule show the weekly schedule of possible
    outages when that option is on. Stabilization outages reported for the
    address are left out: the schedule already shows them.
    """

    def __init__(self, coordinator: DtekCoordinator) -> None:
        """Initialize the calendar."""
        super().__init__(coordinator, "outages")

    def _text(self) -> dict[str, str]:
        language = self.hass.config.language.split("-")[0]
        return CALENDAR_TEXT.get(language, CALENDAR_TEXT["en"])

    def _events(self) -> list[CalendarEvent]:
        coordinator = self.coordinator
        data = coordinator.data
        tz = coordinator.tz
        text = self._text()
        group = f"{text['group']} {group_name(data.group)}"
        events = [
            CalendarEvent(
                start=item.start.astimezone(tz),
                end=item.end.astimezone(tz),
                summary=text["outage"] if item.kind != SLOT_MAYBE else text["possible"],
                description=group,
                uid=f"{coordinator.config_entry.entry_id}-{item.start.isoformat()}",
            )
            for item in intervals(data.days, tz, (SLOT_OFF, SLOT_MAYBE))
        ]
        if coordinator.show_possible and data.preset:
            today, _ = slot_at(dt_util.utcnow(), tz)
            weekly = possible_days(data.preset, today, POSSIBLE_DAYS_AHEAD, data.days)
            events.extend(
                CalendarEvent(
                    start=item.start.astimezone(tz),
                    end=item.end.astimezone(tz),
                    summary=text["possible"],
                    description=f"{group}\n{text['weekly']}",
                    uid=(
                        f"{coordinator.config_entry.entry_id}-possible-"
                        f"{item.start.isoformat()}"
                    ),
                )
                for item in intervals(weekly, tz, (SLOT_MAYBE,))
            )
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
                    description=group,
                    location=(
                        f"{coordinator.settlement}, {coordinator.street}, "
                        f"{coordinator.house}"
                    ),
                    uid=f"{coordinator.config_entry.entry_id}-address-"
                    f"{outage.start.isoformat()}",
                )
            )
        return sorted(events, key=lambda e: e.start_datetime_local)

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
