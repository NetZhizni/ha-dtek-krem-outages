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
    CONF_LANGUAGE,
    CONF_SHOW_POSSIBLE,
    CONF_WARN_END,
    CONF_WARN_START,
    CONF_WARNING_MINUTES,
    DOMAIN,
    EVENT_BUS,
)
from homeassistant.const import ATTR_ATTRIBUTION, ATTR_ENTITY_ID
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr, entity_registry as er
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


async def test_outage_binary_sensors_are_problems(
    hass: HomeAssistant, fake_dtek: FakeDtek, mock_config_entry: MockConfigEntry
) -> None:
    """``on`` means an outage, so the UI shows Problem / OK, not On / Off."""
    await setup_entry(hass, mock_config_entry)
    for key in ("scheduled_outage", "address_outage"):
        assert state(hass, "binary_sensor", key).attributes["device_class"] == "problem"


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


@pytest.mark.parametrize("options", [{CONF_WARN_START: []}])
async def test_warning_disabled(
    hass: HomeAssistant,
    fake_dtek: FakeDtek,
    mock_config_entry: MockConfigEntry,
    frozen_now: FrozenDateTimeFactory,
) -> None:
    """Nothing ticked turns warnings off."""
    await setup_entry(hass, mock_config_entry)
    events = async_capture_events(hass, EVENT_BUS)
    await move_to(hass, frozen_now, kyiv(TODAY, "11:59"))
    assert [e.data["type"] for e in events] == []


@pytest.mark.parametrize("options", [{CONF_WARNING_MINUTES: 45}])
async def test_legacy_warning_minutes(
    hass: HomeAssistant,
    fake_dtek: FakeDtek,
    mock_config_entry: MockConfigEntry,
    frozen_now: FrozenDateTimeFactory,
) -> None:
    """An entry saved with the single number warns once, before the start."""
    await setup_entry(hass, mock_config_entry)
    events = async_capture_events(hass, EVENT_BUS)
    await move_to(hass, frozen_now, kyiv(TODAY, "11:15"))
    assert [e.data["minutes"] for e in events] == [45]


@pytest.mark.parametrize(
    "options", [{CONF_WARN_START: [30, 5], CONF_WARN_END: [30, 5]}]
)
async def test_several_warnings(
    hass: HomeAssistant,
    fake_dtek: FakeDtek,
    mock_config_entry: MockConfigEntry,
    frozen_now: FrozenDateTimeFactory,
) -> None:
    """Each ticked time warns before the start and before the end."""
    await setup_entry(hass, mock_config_entry)
    events = async_capture_events(hass, EVENT_BUS)
    mock_config_entry.runtime_data.update_interval = timedelta(days=1)

    for at in ("11:30", "11:55", "12:00", "13:30", "13:55", "14:00"):
        await move_to(hass, frozen_now, kyiv(TODAY, at))
    assert [(e.data["type"], e.data.get("minutes")) for e in events] == [
        ("outage_warning", 30),
        ("outage_warning", 5),
        ("outage_started", None),
        ("outage_end_warning", 30),
        ("outage_end_warning", 5),
        ("outage_ended", None),
    ]
    ending = events[3].data
    assert ending["start"] == "2026-10-18T12:00:00+03:00"
    assert ending["end"] == "2026-10-18T14:00:00+03:00"
    assert state(hass, "event", "events").attributes["event_type"] == "outage_ended"


@pytest.mark.parametrize("options", [{CONF_WARN_START: [30, 20]}])
async def test_soon_outage_gives_one_warning(
    hass: HomeAssistant, fake_dtek: FakeDtek, mock_config_entry: MockConfigEntry
) -> None:
    """An outage that starts within several thresholds is announced only once."""
    await setup_entry(hass, mock_config_entry)
    events = async_capture_events(hass, EVENT_BUS)
    # Now is 10:10: the outage starts in 20 minutes, inside both thresholds.
    fake_dtek.days[TODAY][GROUP] = slots(("10:30", "11:00"), ("12:00", "14:00"))
    fake_dtek.update = "18.10.2026 10:05"
    await mock_config_entry.runtime_data.async_refresh()
    await hass.async_block_till_done()
    warnings = [e.data["minutes"] for e in events if e.data["type"] == "outage_warning"]
    assert warnings == [20]
    await mock_config_entry.runtime_data.async_refresh()
    await hass.async_block_till_done()
    assert len([e for e in events if e.data["type"] == "outage_warning"]) == 1


@pytest.mark.parametrize("options", [{CONF_WARN_START: [], CONF_WARN_END: [30, 5]}])
async def test_late_end_warning_is_sent_once(
    hass: HomeAssistant,
    fake_dtek: FakeDtek,
    mock_config_entry: MockConfigEntry,
    frozen_now: FrozenDateTimeFactory,
) -> None:
    """A wake-up inside every threshold gives one "ending" event, not one each."""
    await setup_entry(hass, mock_config_entry)
    events = async_capture_events(hass, EVENT_BUS)
    mock_config_entry.runtime_data.update_interval = timedelta(days=1)
    await move_to(hass, frozen_now, kyiv(TODAY, "12:00"))
    events.clear()
    # The 13:30 timer wakes up late, when 5 minutes are already inside 30 too.
    await move_to(hass, frozen_now, kyiv(TODAY, "13:56"))
    ending = [e.data for e in events if e.data["type"] == "outage_end_warning"]
    assert [w["minutes"] for w in ending] == [4]
    await move_to(hass, frozen_now, kyiv(TODAY, "13:58"))
    assert len([e for e in events if e.data["type"] == "outage_end_warning"]) == 1


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
        mock_config_entry,
        options={**mock_config_entry.options, CONF_LANGUAGE: "en", **options},
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


async def test_ukrainian_names(
    hass: HomeAssistant, fake_dtek: FakeDtek, mock_config_entry: MockConfigEntry
) -> None:
    """Names and calendar texts are Ukrainian by default, even if HA is English."""
    assert hass.config.language == "en"
    await setup_entry(hass, mock_config_entry)
    entity_id = get_entity_id(hass, "sensor", "next_outage")
    assert entity_id.endswith("_next_outage")
    assert hass.states.get(entity_id).attributes["friendly_name"] == (
        f"{TITLE} Наступне відключення"
    )
    entry = er.async_get(hass).async_get(entity_id)
    assert entry.original_name == "Наступне відключення"
    assert state(hass, "event", "events").attributes["friendly_name"] == (
        f"{TITLE} Події відключень"
    )
    calendar = state(hass, "calendar", "outages")
    assert calendar.attributes["friendly_name"] == f"{TITLE} Відключення"
    assert calendar.attributes["message"] == "Відключення світла"
    assert calendar.attributes["description"] == "Черга 3.1"
    # IDs of the newer sensors come from their English names, as in the README.
    for key, suffix in (
        ("connection", "_dtek_connection"),
        ("restoration", "_estimated_restoration"),
        ("address_status", "_address_status"),
    ):
        assert get_entity_id(hass, "sensor", key).endswith(suffix)
    assert state(hass, "sensor", "connection").attributes["friendly_name"] == (
        f"{TITLE} Зв'язок з ДТЕК"
    )


@pytest.mark.parametrize("options", [{CONF_LANGUAGE: "en"}])
async def test_english_names(
    hass: HomeAssistant, fake_dtek: FakeDtek, mock_config_entry: MockConfigEntry
) -> None:
    """The English language option gives English names, even if HA is Ukrainian."""
    hass.config.language = "uk"
    await setup_entry(hass, mock_config_entry)
    entity_id = get_entity_id(hass, "binary_sensor", "scheduled_outage")
    assert entity_id.endswith("_scheduled_outage")
    assert hass.states.get(entity_id).attributes["friendly_name"] == (
        f"{TITLE} Scheduled outage"
    )
    assert state(hass, "calendar", "outages").attributes["message"] == "Power outage"


@pytest.mark.parametrize("options", [{CONF_LANGUAGE: "ru"}])
async def test_russian_names(
    hass: HomeAssistant, fake_dtek: FakeDtek, mock_config_entry: MockConfigEntry
) -> None:
    """The Russian language option gives Russian names and calendar texts."""
    await setup_entry(hass, mock_config_entry)
    entity_id = get_entity_id(hass, "sensor", "next_outage")
    assert entity_id.endswith("_next_outage")
    assert hass.states.get(entity_id).attributes["friendly_name"] == (
        f"{TITLE} Следующее отключение"
    )
    calendar = state(hass, "calendar", "outages")
    assert calendar.attributes["message"] == "Отключение света"
    assert calendar.attributes["description"] == "Очередь 3.1"


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


async def test_connection_and_freshness(
    hass: HomeAssistant, fake_dtek: FakeDtek, mock_config_entry: MockConfigEntry
) -> None:
    """The connection sensor and ``data_status`` follow what answered."""
    await setup_entry(hass, mock_config_entry)
    connection = state(hass, "sensor", "connection")
    assert connection.state == "ok"
    assert connection.attributes["device_class"] == "enum"
    assert connection.attributes["consecutive_failures"] == 0
    assert connection.attributes["update_interval_minutes"] == 5
    assert connection.attributes["daily_schedule_shown"] is True
    assert connection.attributes["weekly_schedule_shown"] is True
    assert connection.attributes["blocked"] is False
    for platform, key in (
        ("sensor", "next_outage"),
        ("sensor", "outages_today"),
        ("binary_sensor", "scheduled_outage"),
        ("calendar", "outages"),
    ):
        attributes = state(hass, platform, key).attributes
        assert attributes["data_status"] == "current", key
        assert attributes["last_verified_at"] == "2026-10-18T07:10:00+00:00", key

    fake_dtek.ajax_error = TimeoutError()
    fake_dtek.mirror_error = TimeoutError()
    await mock_config_entry.runtime_data.async_refresh()
    await hass.async_block_till_done()
    connection = state(hass, "sensor", "connection")
    assert connection.state == "offline"
    assert connection.attributes["consecutive_failures"] == 1
    assert connection.attributes["last_error"].startswith("DTEK:")
    assert state(hass, "sensor", "next_outage").attributes["data_status"] == "stale"
    assert state(hass, "sensor", "address_status").state == "unavailable"


async def test_address_status_sensors(
    hass: HomeAssistant, fake_dtek: FakeDtek, mock_config_entry: MockConfigEntry
) -> None:
    """The status and the estimated restoration of the address."""
    await setup_entry(hass, mock_config_entry)
    status = state(hass, "sensor", "address_status")
    assert status.state == "none"
    assert status.attributes["options"] == [
        "none",
        "stabilization",
        "emergency",
        "planned",
        "other",
    ]
    assert state(hass, "sensor", "restoration").state == "unknown"

    fake_dtek.houses[HOUSE] = make_house(
        reason="Аварійні ремонтні роботи",
        start="09:50 18.10.2026",
        end="13:00 18.10.2026",
    )
    await mock_config_entry.runtime_data.async_refresh()
    await hass.async_block_till_done()
    status = state(hass, "sensor", "address_status")
    assert status.state == "emergency"
    assert status.attributes["reason"] == "Аварійні ремонтні роботи"
    assert status.attributes["active"] is True
    restoration = state(hass, "sensor", "restoration")
    assert dt_util.parse_datetime(restoration.state) == kyiv(TODAY, "13:00")
    assert restoration.attributes["reason"] == "Аварійні ремонтні роботи"


async def test_calendar_hides_weekly_with_dtek(
    hass: HomeAssistant, fake_dtek: FakeDtek, mock_config_entry: MockConfigEntry
) -> None:
    """The weekly schedule is left out while the DTEK page hides it."""
    fake_dtek.flags["showTablePlan"] = False
    await setup_entry(hass, mock_config_entry)
    entity_id = get_entity_id(hass, "calendar", "outages")
    response = await hass.services.async_call(
        "calendar",
        "get_events",
        {
            ATTR_ENTITY_ID: entity_id,
            "start_date_time": kyiv(TODAY, "00:00"),
            "end_date_time": kyiv(TODAY + timedelta(days=7), "00:00"),
        },
        blocking=True,
        return_response=True,
    )
    starts = [e["start"] for e in response[entity_id]["events"]]
    assert starts == ["2026-10-18T12:00:00+03:00", "2026-10-18T18:00:00+03:00"]
    assert (
        state(hass, "sensor", "connection").attributes["weekly_schedule_shown"] is False
    )
