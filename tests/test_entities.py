"""Tests for the entities and the time based events."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from freezegun.api import FrozenDateTimeFactory
import pytest
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_capture_events,
    async_fire_time_changed,
)

from custom_components.dtek_krem_outages.const import (
    ATTRIBUTION,
    CONF_SHOW_POSSIBLE,
    CONF_WARNING_MINUTES,
    DOMAIN,
    EVENT_BUS,
)
from homeassistant.const import ATTR_ATTRIBUTION, ATTR_ENTITY_ID
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.util import dt as dt_util

from .conftest import (
    ENTRY_ID,
    GROUP,
    HOUSE,
    TITLE,
    TODAY,
    TOMORROW,
    FakeDtek,
    get_entity_id,
    kyiv,
    make_house,
    setup_entry,
    slots,
)


async def move_to(
    hass: HomeAssistant, frozen_now: FrozenDateTimeFactory, when: Any
) -> None:
    """Move the clock and run the timers that became due."""
    frozen_now.move_to(when)
    async_fire_time_changed(hass)
    await hass.async_block_till_done()


def state(hass: HomeAssistant, platform: str, key: str) -> Any:
    """Return the state object of an entity of the test entry."""
    return hass.states.get(get_entity_id(hass, platform, key))


async def test_sensor_states(
    hass: HomeAssistant, fake_dtek: FakeDtek, mock_config_entry: MockConfigEntry
) -> None:
    """Sensors show the group, the next outage and the day totals."""
    await setup_entry(hass, mock_config_entry)

    group = state(hass, "sensor", "group")
    assert group.state == "3.1"
    assert group.attributes["group_id"] == GROUP
    assert group.attributes["groups_at_address"] == ["3.1"]
    assert group.attributes["house"] == HOUSE
    assert group.attributes[ATTR_ATTRIBUTION] == ATTRIBUTION

    next_outage = state(hass, "sensor", "next_outage")
    assert dt_util.parse_datetime(next_outage.state) == kyiv(TODAY, "12:00")
    assert next_outage.attributes["end"] == "2026-10-18T14:00:00+03:00"
    assert next_outage.attributes["duration_minutes"] == 120

    assert state(hass, "sensor", "outage_end").state == "unknown"

    today = state(hass, "sensor", "outages_today")
    assert today.state == "4.5"
    assert today.attributes["unit_of_measurement"] == "h"
    assert today.attributes["outages_text"] == "12:00–14:00, 18:00–20:30"
    assert today.attributes["published"] is True

    tomorrow = state(hass, "sensor", "outages_tomorrow")
    assert tomorrow.state == "unknown"
    assert tomorrow.attributes["published"] is False

    updated = state(hass, "sensor", "schedule_updated")
    assert dt_util.parse_datetime(updated.state) == kyiv(TODAY, "09:00")
    assert updated.attributes["source"] == "dtek"

    assert state(hass, "binary_sensor", "scheduled_outage").state == "off"
    address = state(hass, "binary_sensor", "address_outage")
    assert address.state == "off"
    assert address.attributes["reason"] is None

    device = dr.async_get(hass).async_get_device_by_identifier(
        (DOMAIN, ENTRY_ID), ENTRY_ID
    )
    assert device is not None
    assert device.name == TITLE
    assert device.entry_type is dr.DeviceEntryType.SERVICE


async def test_outage_edges_and_warning(
    hass: HomeAssistant,
    fake_dtek: FakeDtek,
    mock_config_entry: MockConfigEntry,
    frozen_now: FrozenDateTimeFactory,
) -> None:
    """States switch and events fire at the exact times, without polling."""
    await setup_entry(hass, mock_config_entry)
    events = async_capture_events(hass, EVENT_BUS)
    # Stop polling so only the schedule timer acts.
    mock_config_entry.runtime_data.update_interval = timedelta(days=1)

    await move_to(hass, frozen_now, kyiv(TODAY, "11:29"))
    assert events == []

    await move_to(hass, frozen_now, kyiv(TODAY, "11:30"))
    assert [e.data["type"] for e in events] == ["outage_warning"]
    warning = events[0].data
    assert warning["minutes"] == 30
    assert warning["start"] == "2026-10-18T12:00:00+03:00"
    assert warning["end"] == "2026-10-18T14:00:00+03:00"
    assert warning["duration_minutes"] == 120
    assert state(hass, "event", "events").attributes["event_type"] == "outage_warning"

    await move_to(hass, frozen_now, kyiv(TODAY, "12:00"))
    assert events[-1].data["type"] == "outage_started"
    assert state(hass, "binary_sensor", "scheduled_outage").state == "on"
    outage_end = state(hass, "sensor", "outage_end")
    assert dt_util.parse_datetime(outage_end.state) == kyiv(TODAY, "14:00")
    next_outage = state(hass, "sensor", "next_outage")
    assert dt_util.parse_datetime(next_outage.state) == kyiv(TODAY, "18:00")

    await move_to(hass, frozen_now, kyiv(TODAY, "14:00"))
    ended = events[-1].data
    assert ended["type"] == "outage_ended"
    assert ended["start"] == "2026-10-18T12:00:00+03:00"
    assert ended["next_start"] == "2026-10-18T18:00:00+03:00"
    assert state(hass, "binary_sensor", "scheduled_outage").state == "off"
    assert state(hass, "sensor", "outage_end").state == "unknown"

    types = [e.data["type"] for e in events]
    assert types == ["outage_warning", "outage_started", "outage_ended"]


async def test_warning_for_soon_outage_after_change(
    hass: HomeAssistant, fake_dtek: FakeDtek, mock_config_entry: MockConfigEntry
) -> None:
    """A new outage starting within the warning time is announced at once."""
    await setup_entry(hass, mock_config_entry)
    events = async_capture_events(hass, EVENT_BUS)
    fake_dtek.days[TODAY][GROUP] = slots(("10:30", "11:00"), ("12:00", "14:00"))
    fake_dtek.update = "18.10.2026 10:05"
    await mock_config_entry.runtime_data.async_refresh()
    await hass.async_block_till_done()
    warnings = [e.data for e in events if e.data["type"] == "outage_warning"]
    assert len(warnings) == 1
    assert warnings[0]["minutes"] == 20
    # Not repeated on the next update.
    await mock_config_entry.runtime_data.async_refresh()
    await hass.async_block_till_done()
    assert len([e for e in events if e.data["type"] == "outage_warning"]) == 1


@pytest.mark.parametrize("options", [{CONF_WARNING_MINUTES: 0}])
async def test_warning_disabled(
    hass: HomeAssistant,
    fake_dtek: FakeDtek,
    mock_config_entry: MockConfigEntry,
    frozen_now: FrozenDateTimeFactory,
) -> None:
    """0 minutes turns warnings off."""
    await setup_entry(hass, mock_config_entry)
    events = async_capture_events(hass, EVENT_BUS)
    await move_to(hass, frozen_now, kyiv(TODAY, "11:59"))
    assert [e.data["type"] for e in events] == []


async def test_midnight_rollover(
    hass: HomeAssistant,
    fake_dtek: FakeDtek,
    mock_config_entry: MockConfigEntry,
    frozen_now: FrozenDateTimeFactory,
) -> None:
    """Tomorrow becomes today at local midnight."""
    fake_dtek.days[TOMORROW] = {GROUP: slots(("06:00", "07:00"))}
    await setup_entry(hass, mock_config_entry)
    mock_config_entry.runtime_data.update_interval = timedelta(days=1)
    assert state(hass, "sensor", "outages_tomorrow").state == "1.0"

    await move_to(hass, frozen_now, kyiv(TOMORROW, "00:00"))
    assert state(hass, "sensor", "outages_today").state == "1.0"
    assert state(hass, "sensor", "outages_tomorrow").state == "unknown"


async def test_address_outage_sensor(
    hass: HomeAssistant,
    fake_dtek: FakeDtek,
    mock_config_entry: MockConfigEntry,
    frozen_now: FrozenDateTimeFactory,
) -> None:
    """The address sensor follows the reported start and end."""
    fake_dtek.houses[HOUSE] = make_house(
        reason="Аварійні ремонтні роботи",
        start="09:50 18.10.2026",
        end="11:00 18.10.2026",
    )
    await setup_entry(hass, mock_config_entry)
    mock_config_entry.runtime_data.update_interval = timedelta(days=1)

    address = state(hass, "binary_sensor", "address_outage")
    assert address.state == "on"
    assert address.attributes["reason"] == "Аварійні ремонтні роботи"
    assert address.attributes["kind"] == "emergency"
    assert address.attributes["end"] == "2026-10-18T11:00:00+03:00"

    await move_to(hass, frozen_now, kyiv(TODAY, "11:00"))
    assert state(hass, "binary_sensor", "address_outage").state == "off"


@pytest.mark.parametrize(
    ("options", "possible_expected"),
    [({}, True), ({CONF_SHOW_POSSIBLE: False}, False)],
)
async def test_calendar(
    hass: HomeAssistant,
    fake_dtek: FakeDtek,
    mock_config_entry: MockConfigEntry,
    options: dict[str, Any],
    possible_expected: bool,
) -> None:
    """The calendar lists outages, possible outages and address works."""
    mock_config_entry.add_to_hass(hass)
    hass.config_entries.async_update_entry(
        mock_config_entry, options={**mock_config_entry.options, **options}
    )
    fake_dtek.houses[HOUSE] = make_house(
        reason="Планові ремонтні роботи",
        start="09:00 19.10.2026",
        end="17:00 19.10.2026",
    )
    await setup_entry(hass, mock_config_entry)
    entity_id = get_entity_id(hass, "calendar", "outages")

    calendar = hass.states.get(entity_id)
    assert calendar.attributes["message"] == "Power outage"
    assert calendar.attributes["description"] == "Group 3.1"

    response = await hass.services.async_call(
        "calendar",
        "get_events",
        {
            ATTR_ENTITY_ID: entity_id,
            "start_date_time": kyiv(TODAY, "00:00"),
            "end_date_time": kyiv(TODAY + timedelta(days=2), "00:00"),
        },
        blocking=True,
        return_response=True,
    )
    events = response[entity_id]["events"]
    summaries = [(e["summary"], e["start"]) for e in events]
    assert ("Power outage", "2026-10-18T12:00:00+03:00") in summaries
    assert ("Power outage", "2026-10-18T18:00:00+03:00") in summaries
    assert ("Планові ремонтні роботи", "2026-10-19T09:00:00+03:00") in summaries
    # Today has an actual schedule, so only tomorrow shows the weekly one.
    possible = [s for s in summaries if s[0] == "Possible outage"]
    if possible_expected:
        assert possible == [("Possible outage", "2026-10-19T16:00:00+03:00")]
    else:
        assert possible == []


async def test_calendar_in_ukrainian(
    hass: HomeAssistant, fake_dtek: FakeDtek, mock_config_entry: MockConfigEntry
) -> None:
    """Calendar texts follow the Home Assistant language."""
    hass.config.language = "uk"
    await setup_entry(hass, mock_config_entry)
    calendar = state(hass, "calendar", "outages")
    assert calendar.attributes["message"] == "Відключення світла"
    assert calendar.attributes["description"] == "Черга 3.1"


async def test_late_timer_reports_both_edges(
    hass: HomeAssistant,
    fake_dtek: FakeDtek,
    mock_config_entry: MockConfigEntry,
    frozen_now: FrozenDateTimeFactory,
) -> None:
    """If the clock jumps past an end and the next start, both are reported."""
    fake_dtek.days[TODAY][GROUP] = slots(("12:00", "14:00"), ("14:30", "16:00"))
    await setup_entry(hass, mock_config_entry)
    mock_config_entry.runtime_data.update_interval = timedelta(days=1)
    await move_to(hass, frozen_now, kyiv(TODAY, "12:10"))
    events = async_capture_events(hass, EVENT_BUS)

    await move_to(hass, frozen_now, kyiv(TODAY, "14:40"))
    data = [(e.data["type"], e.data["start"]) for e in events]
    assert data == [
        ("outage_ended", "2026-10-18T12:00:00+03:00"),
        ("outage_started", "2026-10-18T14:30:00+03:00"),
    ]


async def test_extended_outage_is_not_restarted(
    hass: HomeAssistant,
    fake_dtek: FakeDtek,
    mock_config_entry: MockConfigEntry,
    frozen_now: FrozenDateTimeFactory,
) -> None:
    """A schedule change that extends the running outage fires no edge."""
    await setup_entry(hass, mock_config_entry)
    mock_config_entry.runtime_data.update_interval = timedelta(days=1)
    await move_to(hass, frozen_now, kyiv(TODAY, "12:10"))
    events = async_capture_events(hass, EVENT_BUS)

    fake_dtek.days[TODAY][GROUP] = slots(("12:00", "15:00"), ("18:00", "20:30"))
    fake_dtek.update = "18.10.2026 12:05"
    await mock_config_entry.runtime_data.async_refresh()
    await hass.async_block_till_done()
    assert [e.data["type"] for e in events] == ["schedule_changed"]
    outage_end = state(hass, "sensor", "outage_end")
    assert dt_util.parse_datetime(outage_end.state) == kyiv(TODAY, "15:00")
