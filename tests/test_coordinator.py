"""Tests for updates, merging, storage and change events."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

import aiohttp
from freezegun.api import FrozenDateTimeFactory
import pytest
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_capture_events,
    async_fire_time_changed,
)

from custom_components.dtek_krem_outages.const import (
    CONF_EXCLUDED_GROUPS,
    CONF_EXTRA_GROUPS,
    CONF_GROUP,
    CONF_GROUPS_MODE,
    CONF_USE_MIRROR,
    DEFAULT_OPTIONS,
    DOMAIN,
    EVENT_BUS,
    FORCE_UPDATE_FACT,
    SOURCE_DTEK,
    SOURCE_MIRROR,
    STORAGE_VERSION,
    storage_key,
)
from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import EVENT_HOMEASSISTANT_STARTED, STATE_UNAVAILABLE
from homeassistant.core import CoreState, Event, HomeAssistant
from homeassistant.helpers import entity_registry as er

from .conftest import (
    ENTRY_ID,
    GROUP,
    HOUSE,
    SETTLEMENT,
    STREET,
    TODAY,
    TOMORROW,
    FakeDtek,
    get_entity_id,
    kyiv,
    make_house,
    setup_entry,
    slots,
)

STORE_KEY = storage_key(ENTRY_ID)
ADDRESS_KEY = f"{SETTLEMENT}|{STREET}|{HOUSE}"


def stored(hass_storage: dict[str, Any]) -> dict[str, Any]:
    """Return the state written to the Store."""
    return hass_storage[STORE_KEY]["data"]


def store_payload(**data: Any) -> dict[str, Any]:
    """Return a Store file for the test entry."""
    return {
        "version": STORAGE_VERSION,
        "minor_version": 1,
        "key": STORE_KEY,
        "data": {"address": ADDRESS_KEY, "group": GROUP, **data},
    }


def bus_events(events: list[Event], event_type: str | None = None) -> list[dict]:
    """Return the data of captured events, optionally of one type."""
    return [e.data for e in events if event_type in (None, e.data["type"])]


async def refresh(hass: HomeAssistant, entry: MockConfigEntry) -> None:
    """Run a coordinator update."""
    await entry.runtime_data.async_refresh()
    await hass.async_block_till_done()


async def test_setup_and_unload(
    hass: HomeAssistant,
    fake_dtek: FakeDtek,
    mock_config_entry: MockConfigEntry,
    hass_storage: dict[str, Any],
) -> None:
    """The first update records the schedule silently and stores it."""
    events = async_capture_events(hass, EVENT_BUS)
    await setup_entry(hass, mock_config_entry)
    assert mock_config_entry.state is ConfigEntryState.LOADED

    data = mock_config_entry.runtime_data.data
    assert data.days == {TODAY: slots(("12:00", "14:00"), ("18:00", "20:30"))}
    assert data.source == SOURCE_DTEK
    assert data.fact_update == "18.10.2026 09:00"
    assert data.preset[TODAY.isoweekday()] == slots(possible=(("16:00", "20:00"),))
    assert bus_events(events) == []

    saved = stored(hass_storage)
    assert saved["address"] == ADDRESS_KEY
    assert saved["group"] == GROUP
    assert saved["fact_update"] == "18.10.2026 09:00"
    assert saved["days"] == {TODAY.isoformat(): data.days[TODAY]}
    # The first request forces the schedule.
    assert fake_dtek.schedule_forms[0]["data[2][value]"] == FORCE_UPDATE_FACT

    assert await hass.config_entries.async_unload(mock_config_entry.entry_id)
    assert mock_config_entry.state is ConfigEntryState.NOT_LOADED


async def test_unchanged_version_skips_schedule(
    hass: HomeAssistant, fake_dtek: FakeDtek, mock_config_entry: MockConfigEntry
) -> None:
    """Later requests send the known version and get only the houses."""
    await setup_entry(hass, mock_config_entry)
    await refresh(hass, mock_config_entry)
    assert fake_dtek.schedule_forms[-1]["data[2][value]"] == "18.10.2026 09:00"
    assert mock_config_entry.runtime_data.data.days[TODAY] == slots(
        ("12:00", "14:00"), ("18:00", "20:30")
    )


async def test_schedule_change_event_and_frozen_past(
    hass: HomeAssistant,
    fake_dtek: FakeDtek,
    mock_config_entry: MockConfigEntry,
    hass_storage: dict[str, Any],
) -> None:
    """A new version changes the future, keeps the past and fires an event."""
    fake_dtek.days[TODAY][GROUP] = slots(("08:00", "10:00"), ("12:00", "14:00"))
    await setup_entry(hass, mock_config_entry)
    events = async_capture_events(hass, EVENT_BUS)

    # DTEK rewrites the morning (already past at 10:10) and moves the evening.
    fake_dtek.days[TODAY][GROUP] = slots(("06:00", "07:00"), ("16:00", "17:30"))
    fake_dtek.update = "18.10.2026 10:05"
    await refresh(hass, mock_config_entry)

    data = mock_config_entry.runtime_data.data
    assert data.days[TODAY] == slots(("08:00", "10:00"), ("16:00", "17:30"))
    assert data.fact_update == "18.10.2026 10:05"
    assert stored(hass_storage)["days"][TODAY.isoformat()] == data.days[TODAY]

    changed = bus_events(events, "schedule_changed")
    assert len(changed) == 1
    event = changed[0]
    assert event["date"] == TODAY.isoformat()
    assert event["day"] == "today"
    assert event["outages_text"] == "08:00–10:00, 16:00–17:30"
    assert event["outages"] == [
        {"start": "2026-10-18T08:00:00+03:00", "end": "2026-10-18T10:00:00+03:00"},
        {"start": "2026-10-18T16:00:00+03:00", "end": "2026-10-18T17:30:00+03:00"},
    ]
    assert event["outage_minutes"] == 210
    assert event["previous_outages_text"] == "08:00–10:00, 12:00–14:00"
    assert event["previous_outage_minutes"] == 240
    assert event["schedule_updated"] == "2026-10-18T10:05:00+03:00"
    assert event["group"] == GROUP
    assert event["group_name"] == "3.1"
    assert event["settlement"] == SETTLEMENT
    assert event["config_entry_id"] == ENTRY_ID
    assert event["source"] == SOURCE_DTEK

    state = hass.states.get(get_entity_id(hass, "event", "events"))
    assert state.attributes["event_type"] == "schedule_changed"
    assert state.attributes["outages_text"] == "08:00–10:00, 16:00–17:30"


async def test_change_only_in_the_past_is_silent(
    hass: HomeAssistant, fake_dtek: FakeDtek, mock_config_entry: MockConfigEntry
) -> None:
    """A new version that differs only for finished slots fires nothing."""
    await setup_entry(hass, mock_config_entry)
    events = async_capture_events(hass, EVENT_BUS)
    fake_dtek.days[TODAY][GROUP] = slots(
        ("07:00", "08:00"), ("12:00", "14:00"), ("18:00", "20:30")
    )
    fake_dtek.update = "18.10.2026 10:05"
    await refresh(hass, mock_config_entry)
    assert bus_events(events) == []
    assert mock_config_entry.runtime_data.data.days[TODAY] == slots(
        ("12:00", "14:00"), ("18:00", "20:30")
    )


async def test_tomorrow_published(
    hass: HomeAssistant, fake_dtek: FakeDtek, mock_config_entry: MockConfigEntry
) -> None:
    """A day that appears for the first time is announced as published."""
    await setup_entry(hass, mock_config_entry)
    events = async_capture_events(hass, EVENT_BUS)
    fake_dtek.days[TOMORROW] = {GROUP: slots(("00:00", "03:00"))}
    fake_dtek.update = "18.10.2026 20:00"
    await refresh(hass, mock_config_entry)

    published = bus_events(events, "schedule_published")
    assert len(published) == 1
    assert published[0]["date"] == TOMORROW.isoformat()
    assert published[0]["day"] == "tomorrow"
    assert published[0]["outages_text"] == "00:00–03:00"
    assert "previous_outages" not in published[0]
    assert bus_events(events, "schedule_changed") == []


async def test_mirror_fallback(
    hass: HomeAssistant, fake_dtek: FakeDtek, mock_config_entry: MockConfigEntry
) -> None:
    """When DTEK fails, a newer mirror schedule is used."""
    await setup_entry(hass, mock_config_entry)
    events = async_capture_events(hass, EVENT_BUS)
    assert fake_dtek.mirror_requests == 0

    fake_dtek.ajax_error = aiohttp.ClientConnectionError()
    fake_dtek.mirror_days = {TODAY: {GROUP: slots(("12:00", "15:00"))}}
    fake_dtek.mirror_update = "18.10.2026 10:00"
    await refresh(hass, mock_config_entry)

    data = mock_config_entry.runtime_data.data
    assert data.source == SOURCE_MIRROR
    assert data.days[TODAY] == slots(("12:00", "15:00"))
    assert data.fetch_ok
    assert data.last_error.startswith("DTEK:")
    assert [e["source"] for e in bus_events(events, "schedule_changed")] == [
        SOURCE_MIRROR
    ]
    assert (
        hass.states.get(get_entity_id(hass, "binary_sensor", "address_outage")).state
        == STATE_UNAVAILABLE
    )
    assert hass.states.get(get_entity_id(hass, "sensor", "next_outage")).state != (
        STATE_UNAVAILABLE
    )

    # An older or equal mirror version changes nothing.
    fake_dtek.mirror_days = {TODAY: {GROUP: slots()}}
    fake_dtek.mirror_update = "18.10.2026 08:00"
    await refresh(hass, mock_config_entry)
    assert mock_config_entry.runtime_data.data.days[TODAY] == slots(("12:00", "15:00"))


async def test_mirror_disabled(
    hass: HomeAssistant,
    fake_dtek: FakeDtek,
    mock_config_entry: MockConfigEntry,
    options: dict[str, Any],
) -> None:
    """Without the backup source the mirror is never asked."""
    mock_config_entry.add_to_hass(hass)
    hass.config_entries.async_update_entry(
        mock_config_entry, options={**options, CONF_USE_MIRROR: False}
    )
    await setup_entry(hass, mock_config_entry)
    fake_dtek.ajax_error = aiohttp.ClientConnectionError()
    await refresh(hass, mock_config_entry)
    assert fake_dtek.mirror_requests == 0
    assert not mock_config_entry.runtime_data.data.fetch_ok


async def test_both_sources_down_keep_stored_schedule(
    hass: HomeAssistant, fake_dtek: FakeDtek, mock_config_entry: MockConfigEntry
) -> None:
    """The last known schedule keeps working while nothing answers."""
    await setup_entry(hass, mock_config_entry)
    fake_dtek.ajax_error = aiohttp.ClientConnectionError()
    fake_dtek.mirror_error = aiohttp.ClientConnectionError()
    await refresh(hass, mock_config_entry)

    coordinator = mock_config_entry.runtime_data
    assert coordinator.last_update_success
    assert not coordinator.data.fetch_ok
    assert "mirror:" in coordinator.data.last_error
    assert coordinator.data.days[TODAY] == slots(("12:00", "14:00"), ("18:00", "20:30"))
    assert hass.states.get(get_entity_id(hass, "sensor", "outages_today")).state == (
        "4.5"
    )


async def test_setup_retries_without_any_data(
    hass: HomeAssistant, fake_dtek: FakeDtek, mock_config_entry: MockConfigEntry
) -> None:
    """With no stored schedule and no source, setup is retried."""
    fake_dtek.ajax_error = aiohttp.ClientConnectionError()
    fake_dtek.mirror_error = aiohttp.ClientConnectionError()
    mock_config_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(mock_config_entry.entry_id)
    assert mock_config_entry.state is ConfigEntryState.SETUP_RETRY


async def test_restart_uses_stored_schedule(
    hass: HomeAssistant,
    fake_dtek: FakeDtek,
    mock_config_entry: MockConfigEntry,
    hass_storage: dict[str, Any],
) -> None:
    """After a restart the stored schedule is used when sources are down."""
    hass_storage[STORE_KEY] = store_payload(
        fact_update="18.10.2026 09:30",
        fact_updated_at="2026-10-18T09:30:00+03:00",
        days={TODAY.isoformat(): slots(("11:00", "12:00"))},
        preset={"7": slots()},
        last_success="2026-10-18T06:30:00+00:00",
    )
    fake_dtek.ajax_error = aiohttp.ClientConnectionError()
    fake_dtek.mirror_error = aiohttp.ClientConnectionError()
    await setup_entry(hass, mock_config_entry)

    assert mock_config_entry.state is ConfigEntryState.LOADED
    data = mock_config_entry.runtime_data.data
    assert data.days == {TODAY: slots(("11:00", "12:00"))}
    assert data.fact_update == "18.10.2026 09:30"
    state = hass.states.get(get_entity_id(hass, "sensor", "last_update"))
    assert state.state == "2026-10-18T06:30:00+00:00"


async def test_restart_detects_changes_from_downtime(
    hass: HomeAssistant,
    fake_dtek: FakeDtek,
    mock_config_entry: MockConfigEntry,
    hass_storage: dict[str, Any],
) -> None:
    """Changes published while HA was down are announced after the start."""
    hass_storage[STORE_KEY] = store_payload(
        fact_update="18.10.2026 08:00",
        days={TODAY.isoformat(): slots(("12:00", "13:00"))},
    )
    events = async_capture_events(hass, EVENT_BUS)
    await setup_entry(hass, mock_config_entry)
    assert fake_dtek.schedule_forms[0]["data[2][value]"] == "18.10.2026 08:00"
    assert [e["type"] for e in bus_events(events)] == ["schedule_changed"]


async def test_store_of_another_address_is_ignored(
    hass: HomeAssistant,
    fake_dtek: FakeDtek,
    mock_config_entry: MockConfigEntry,
    hass_storage: dict[str, Any],
) -> None:
    """A reconfigured entry starts with a silent baseline."""
    hass_storage[STORE_KEY] = store_payload(
        address="с. Буча|Без вулиці|1",
        fact_update="18.10.2026 09:00",
        days={TODAY.isoformat(): slots(("00:00", "24:00"))},
    )
    events = async_capture_events(hass, EVENT_BUS)
    await setup_entry(hass, mock_config_entry)
    assert bus_events(events) == []
    assert fake_dtek.schedule_forms[0]["data[2][value]"] == FORCE_UPDATE_FACT
    assert mock_config_entry.runtime_data.data.days[TODAY] == slots(
        ("12:00", "14:00"), ("18:00", "20:30")
    )


async def test_store_of_another_group_keeps_history_only(
    hass: HomeAssistant,
    fake_dtek: FakeDtek,
    mock_config_entry: MockConfigEntry,
    hass_storage: dict[str, Any],
) -> None:
    """After choosing another group the past stays, the future is refetched."""
    yesterday = TODAY - timedelta(days=1)
    hass_storage[STORE_KEY] = store_payload(
        group="GPV1.1",
        fact_update="18.10.2026 09:00",
        days={
            yesterday.isoformat(): slots(("10:00", "11:00")),
            TODAY.isoformat(): slots(("00:00", "01:00")),
            TOMORROW.isoformat(): slots(("05:00", "06:00")),
        },
    )
    events = async_capture_events(hass, EVENT_BUS)
    await setup_entry(hass, mock_config_entry)
    assert bus_events(events) == []
    days = mock_config_entry.runtime_data.data.days
    assert days[yesterday] == slots(("10:00", "11:00"))
    assert days[TODAY] == slots(
        ("00:00", "01:00"), ("12:00", "14:00"), ("18:00", "20:30")
    )
    assert TOMORROW not in days


async def test_group_change_by_dtek(
    hass: HomeAssistant, fake_dtek: FakeDtek, mock_config_entry: MockConfigEntry
) -> None:
    """When DTEK moves the house to another group, the entry follows."""
    await setup_entry(hass, mock_config_entry)
    events = async_capture_events(hass, EVENT_BUS)

    fake_dtek.houses[HOUSE] = make_house(["GPV4.2"])
    await refresh(hass, mock_config_entry)

    assert mock_config_entry.data[CONF_GROUP] == "GPV4.2"
    data = mock_config_entry.runtime_data.data
    assert data.group == "GPV4.2"
    # Finished slots of today keep the old group, the rest is the new group.
    assert data.days[TODAY] == slots(("10:00", "12:00"))
    types = [e["type"] for e in bus_events(events)]
    assert types[0] == "group_changed"
    assert "schedule_changed" in types
    changed = bus_events(events, "group_changed")[0]
    assert changed["previous_group"] == GROUP
    assert changed["group"] == "GPV4.2"
    assert changed["group_name"] == "4.2"
    # The second request forced the schedule of the new group.
    assert fake_dtek.schedule_forms[-1]["data[2][value]"] == FORCE_UPDATE_FACT


async def test_manual_group_is_kept(
    hass: HomeAssistant,
    fake_dtek: FakeDtek,
    mock_config_entry: MockConfigEntry,
    entry_data: dict[str, Any],
) -> None:
    """A group chosen by the user is not replaced."""
    mock_config_entry.add_to_hass(hass)
    hass.config_entries.async_update_entry(
        mock_config_entry, data={**entry_data, "group_manual": True}
    )
    fake_dtek.houses[HOUSE] = make_house(["GPV4.2"])
    await setup_entry(hass, mock_config_entry)
    assert mock_config_entry.runtime_data.data.group == GROUP
    assert mock_config_entry.runtime_data.data.groups_at_address == ["GPV4.2"]


async def test_address_outage_events(
    hass: HomeAssistant, fake_dtek: FakeDtek, mock_config_entry: MockConfigEntry
) -> None:
    """Outages reported for the address fire new, updated and cleared."""
    await setup_entry(hass, mock_config_entry)
    events = async_capture_events(hass, EVENT_BUS)
    reason = "Аварійні ремонтні роботи"

    fake_dtek.houses[HOUSE] = make_house(
        reason=reason, start="09:50 18.10.2026", end="13:00 18.10.2026"
    )
    await refresh(hass, mock_config_entry)
    fake_dtek.houses[HOUSE] = make_house(
        reason=reason, start="09:50 18.10.2026", end="15:00 18.10.2026"
    )
    await refresh(hass, mock_config_entry)
    await refresh(hass, mock_config_entry)
    fake_dtek.houses[HOUSE] = make_house()
    await refresh(hass, mock_config_entry)

    outage_events = bus_events(events, "address_outage")
    assert [e["status"] for e in outage_events] == ["new", "updated", "cleared"]
    assert outage_events[0]["kind"] == "emergency"
    assert outage_events[0]["reason"] == reason
    assert outage_events[0]["start"] == "2026-10-18T09:50:00+03:00"
    assert outage_events[1]["end"] == "2026-10-18T15:00:00+03:00"
    assert outage_events[1]["previous_end"] == "2026-10-18T13:00:00+03:00"


async def test_missing_house(
    hass: HomeAssistant,
    fake_dtek: FakeDtek,
    mock_config_entry: MockConfigEntry,
    caplog: Any,
) -> None:
    """A house that disappeared from DTEK keeps the group and logs once."""
    del fake_dtek.houses[HOUSE]
    await setup_entry(hass, mock_config_entry)
    await refresh(hass, mock_config_entry)
    assert caplog.text.count("is not listed by DTEK") == 1
    assert mock_config_entry.runtime_data.data.group == GROUP


async def test_events_wait_until_started(
    hass: HomeAssistant,
    fake_dtek: FakeDtek,
    mock_config_entry: MockConfigEntry,
    hass_storage: dict[str, Any],
) -> None:
    """Events found during startup are sent once Home Assistant has started."""
    hass_storage[STORE_KEY] = store_payload(fact_update="18.10.2026 08:00", days={})
    hass.set_state(CoreState.not_running)
    events = async_capture_events(hass, EVENT_BUS)
    await setup_entry(hass, mock_config_entry)
    assert bus_events(events) == []

    hass.set_state(CoreState.running)
    hass.bus.async_fire(EVENT_HOMEASSISTANT_STARTED)
    await hass.async_block_till_done()
    assert [e["type"] for e in bus_events(events)] == ["schedule_published"]


async def test_scheduled_update(
    hass: HomeAssistant,
    fake_dtek: FakeDtek,
    mock_config_entry: MockConfigEntry,
    frozen_now: FrozenDateTimeFactory,
) -> None:
    """The coordinator polls with the configured interval."""
    await setup_entry(hass, mock_config_entry)
    count = len(fake_dtek.schedule_forms)
    frozen_now.tick(timedelta(minutes=5, seconds=1))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    assert len(fake_dtek.schedule_forms) == count + 1


async def test_history_is_pruned(
    hass: HomeAssistant,
    fake_dtek: FakeDtek,
    mock_config_entry: MockConfigEntry,
    hass_storage: dict[str, Any],
) -> None:
    """Days older than a week are dropped."""
    old = TODAY - timedelta(days=8)
    kept = TODAY - timedelta(days=7)
    hass_storage[STORE_KEY] = store_payload(
        fact_update="18.10.2026 08:00",
        days={old.isoformat(): slots(), kept.isoformat(): slots()},
    )
    await setup_entry(hass, mock_config_entry)
    assert set(mock_config_entry.runtime_data.data.days) == {kept, TODAY}


async def test_remove_entry_deletes_store(
    hass: HomeAssistant,
    fake_dtek: FakeDtek,
    mock_config_entry: MockConfigEntry,
    hass_storage: dict[str, Any],
    frozen_now: FrozenDateTimeFactory,
) -> None:
    """A pending delayed save does not bring the file back after removal."""
    await setup_entry(hass, mock_config_entry)
    await refresh(hass, mock_config_entry)  # leaves a delayed save pending
    assert await hass.config_entries.async_remove(mock_config_entry.entry_id)
    await hass.async_block_till_done()
    assert STORE_KEY not in hass_storage

    frozen_now.tick(timedelta(minutes=2))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    assert STORE_KEY not in hass_storage


async def test_daily_schedule_hidden_and_shown_again(
    hass: HomeAssistant,
    fake_dtek: FakeDtek,
    mock_config_entry: MockConfigEntry,
    hass_storage: dict[str, Any],
) -> None:
    """While DTEK hides the schedule the future is cleared, then restored."""
    await setup_entry(hass, mock_config_entry)
    events = async_capture_events(hass, EVENT_BUS)

    fake_dtek.flags["showTableFact"] = False
    await refresh(hass, mock_config_entry)
    data = mock_config_entry.runtime_data.data
    assert data.days[TODAY] == slots()
    assert data.publication.daily_hidden
    assert stored(hass_storage)["publication"]["daily"] is False
    changed = bus_events(events, "schedule_changed")
    assert [e["outages_text"] for e in changed] == [""]
    assert changed[0]["previous_outages_text"] == "12:00–14:00, 18:00–20:30"

    # The mirror still has the schedule; it is not used while DTEK hides it.
    fake_dtek.ajax_error = aiohttp.ClientConnectionError()
    fake_dtek.mirror_days = {TODAY: {GROUP: slots(("12:00", "15:00"))}}
    fake_dtek.mirror_update = "18.10.2026 10:00"
    await refresh(hass, mock_config_entry)
    assert mock_config_entry.runtime_data.data.days[TODAY] == slots()

    # Shown again: the whole schedule is asked for, though its version is known.
    fake_dtek.ajax_error = None
    fake_dtek.flags["showTableFact"] = True
    await refresh(hass, mock_config_entry)
    assert fake_dtek.schedule_forms[-1]["data[2][value]"] == FORCE_UPDATE_FACT
    assert mock_config_entry.runtime_data.data.days[TODAY] == slots(
        ("12:00", "14:00"), ("18:00", "20:30")
    )
    assert [e["outages_text"] for e in bus_events(events, "schedule_changed")] == [
        "",
        "12:00–14:00, 18:00–20:30",
    ]


async def test_hidden_from_the_start(
    hass: HomeAssistant, fake_dtek: FakeDtek, mock_config_entry: MockConfigEntry
) -> None:
    """A schedule block hidden at the first update gives no schedule, no events."""
    fake_dtek.flags["showTableSchedule"] = False
    events = async_capture_events(hass, EVENT_BUS)
    await setup_entry(hass, mock_config_entry)
    data = mock_config_entry.runtime_data.data
    assert data.days == {}
    assert data.fact_update == "18.10.2026 09:00"
    assert bus_events(events) == []


async def test_current_outage_hidden(
    hass: HomeAssistant, fake_dtek: FakeDtek, mock_config_entry: MockConfigEntry
) -> None:
    """``showCurOutageParam: false`` leaves the outage of the house out."""
    fake_dtek.flags["showCurOutageParam"] = False
    fake_dtek.houses[HOUSE] = make_house(
        reason="Аварійні ремонтні роботи",
        start="09:50 18.10.2026",
        end="13:00 18.10.2026",
    )
    await setup_entry(hass, mock_config_entry)
    assert mock_config_entry.runtime_data.data.address_outage is None


async def test_house_with_several_records(
    hass: HomeAssistant, fake_dtek: FakeDtek, mock_config_entry: MockConfigEntry
) -> None:
    """A house listed with one record per outage is still found."""
    fake_dtek.houses[HOUSE] = [
        make_house(reason="Планові ремонтні роботи", start="09:00 18.10.2026"),
        make_house(reason="Аварійні ремонтні роботи", start="10:00 18.10.2026"),
    ]
    await setup_entry(hass, mock_config_entry)
    data = mock_config_entry.runtime_data.data
    assert data.groups_at_address == [GROUP]
    assert data.address_outage.kind == "emergency"


async def test_external_operator(
    hass: HomeAssistant,
    fake_dtek: FakeDtek,
    mock_config_entry: MockConfigEntry,
    caplog: Any,
) -> None:
    """A house of another operator is flagged and logged once."""
    fake_dtek.houses[HOUSE] = {**make_house(), "cek": True}
    await setup_entry(hass, mock_config_entry)
    await refresh(hass, mock_config_entry)
    assert mock_config_entry.runtime_data.data.external_operator
    assert caplog.text.count("served by another operator") == 1
    group = hass.states.get(get_entity_id(hass, "sensor", "group"))
    assert group.attributes["external_operator"] is True


async def test_retry_backoff(
    hass: HomeAssistant, fake_dtek: FakeDtek, mock_config_entry: MockConfigEntry
) -> None:
    """Failed updates stretch the interval up to 15 minutes; success resets it."""
    await setup_entry(hass, mock_config_entry)
    coordinator = mock_config_entry.runtime_data
    assert coordinator.update_interval == timedelta(minutes=5)

    fake_dtek.ajax_error = aiohttp.ClientConnectionError()
    for minutes in (5, 10, 15, 15):
        await refresh(hass, mock_config_entry)
        seconds = coordinator.update_interval.total_seconds()
        assert minutes * 60 * 0.9 <= seconds <= minutes * 60 * 1.1
    assert coordinator.data.consecutive_failures == 4
    assert coordinator.data.connection == "mirror"

    fake_dtek.ajax_error = None
    await refresh(hass, mock_config_entry)
    assert coordinator.update_interval == timedelta(minutes=5)
    assert coordinator.data.consecutive_failures == 0
    assert coordinator.data.connection == "ok"


async def test_blocked_by_challenge(
    hass: HomeAssistant, fake_dtek: FakeDtek, mock_config_entry: MockConfigEntry
) -> None:
    """The anti-bot page is told apart from other errors."""
    await setup_entry(hass, mock_config_entry)
    fake_dtek.ajax_text = "<html><script src='/_Incapsula_Resource?x'></script>"
    fake_dtek.mirror_error = aiohttp.ClientConnectionError()
    await refresh(hass, mock_config_entry)
    data = mock_config_entry.runtime_data.data
    assert data.blocked
    assert data.connection == "offline"
    assert data.data_status == "stale"


GROUP_ONLY_DATA = {CONF_GROUP: GROUP, "group_manual": True}


@pytest.mark.parametrize("entry_data", [GROUP_ONLY_DATA])
@pytest.mark.parametrize("options", [{**DEFAULT_OPTIONS, CONF_USE_MIRROR: False}])
async def test_group_only_entry(
    hass: HomeAssistant,
    fake_dtek: FakeDtek,
    mock_config_entry: MockConfigEntry,
    hass_storage: dict[str, Any],
) -> None:
    """Without an address the mirror gives the schedule, whatever the option."""
    registry = er.async_get(hass)
    mock_config_entry.add_to_hass(hass)
    # Left from the time the entry had an address.
    registry.async_get_or_create(
        "binary_sensor",
        DOMAIN,
        f"{ENTRY_ID}_address_outage",
        config_entry=mock_config_entry,
    )
    await setup_entry(hass, mock_config_entry)

    assert fake_dtek.forms == []
    assert fake_dtek.mirror_requests == 1
    data = mock_config_entry.runtime_data.data
    assert data.source == SOURCE_MIRROR
    assert data.connection == "mirror"
    assert data.days[TODAY] == slots(("12:00", "14:00"), ("18:00", "20:30"))
    assert stored(hass_storage)["address"] == ""
    keys = {
        entity.unique_id.removeprefix(f"{ENTRY_ID}_")
        for entity in er.async_entries_for_config_entry(registry, ENTRY_ID)
    }
    assert "address_outage" not in keys
    assert "address_status" not in keys
    assert {"group", "next_outage", "connection", "outages"} <= keys


@pytest.mark.parametrize("entry_data", [GROUP_ONLY_DATA])
async def test_group_only_without_mirror_retries(
    hass: HomeAssistant, fake_dtek: FakeDtek, mock_config_entry: MockConfigEntry
) -> None:
    """Without the mirror an entry by group has nothing and retries setup."""
    fake_dtek.mirror_error = aiohttp.ClientConnectionError()
    mock_config_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(mock_config_entry.entry_id)
    assert mock_config_entry.state is ConfigEntryState.SETUP_RETRY


OTHER = "GPV4.2"
COMBINED = {**DEFAULT_OPTIONS, CONF_GROUPS_MODE: "any"}


async def test_other_group_added_and_removed(
    hass: HomeAssistant,
    fake_dtek: FakeDtek,
    mock_config_entry: MockConfigEntry,
    hass_storage: dict[str, Any],
) -> None:
    """A group DTEK adds is followed at once and dropped after a few misses."""
    await setup_entry(hass, mock_config_entry)
    events = async_capture_events(hass, EVENT_BUS)

    fake_dtek.houses[HOUSE] = make_house([GROUP, OTHER])
    await refresh(hass, mock_config_entry)
    data = mock_config_entry.runtime_data.data
    assert data.group == GROUP
    assert data.extra_groups == [OTHER]
    # The known version came without a schedule: the whole one was asked for.
    assert fake_dtek.schedule_forms[-1]["data[2][value]"] == FORCE_UPDATE_FACT
    assert data.group_days[OTHER] == {TODAY: slots(("08:00", "12:00"))}
    assert data.group_presets[OTHER][TODAY.isoweekday()] == slots()
    # The main group alone is still what the entities show.
    assert data.days[TODAY] == slots(("12:00", "14:00"), ("18:00", "20:30"))
    assert stored(hass_storage)["extra_groups"] == [OTHER]
    # The main group alone stays under ``preset`` for 0.1.4 and older.
    assert stored(hass_storage)["preset"][str(TODAY.isoweekday())] == slots(
        possible=(("16:00", "20:00"),)
    )
    added = bus_events(events, "groups_changed")
    assert len(added) == 1
    assert added[0]["added"] == ["4.2"]
    assert added[0]["removed"] == []
    assert added[0]["extra_groups"] == ["4.2"]
    assert added[0]["group"] == GROUP
    assert bus_events(events, "schedule_changed") == []
    # The next request sends the version again.
    await refresh(hass, mock_config_entry)
    assert fake_dtek.schedule_forms[-1]["data[2][value]"] == "18.10.2026 09:00"

    # A group missing twice and listed again stays.
    fake_dtek.houses[HOUSE] = make_house([GROUP])
    await refresh(hass, mock_config_entry)
    await refresh(hass, mock_config_entry)
    fake_dtek.houses[HOUSE] = make_house([GROUP, OTHER])
    await refresh(hass, mock_config_entry)
    fake_dtek.houses[HOUSE] = make_house([GROUP])
    await refresh(hass, mock_config_entry)
    await refresh(hass, mock_config_entry)
    assert mock_config_entry.runtime_data.data.extra_groups == [OTHER]
    assert len(bus_events(events, "groups_changed")) == 1

    # The third answer in a row without it drops it.
    await refresh(hass, mock_config_entry)
    data = mock_config_entry.runtime_data.data
    assert data.extra_groups == []
    assert OTHER not in data.group_days
    assert data.groups_at_address == [GROUP]
    removed = bus_events(events, "groups_changed")[-1]
    assert removed["added"] == []
    assert removed["removed"] == ["4.2"]
    assert removed["extra_groups"] == []
    assert bus_events(events, "schedule_changed") == []


async def test_glitches_keep_other_groups(
    hass: HomeAssistant, fake_dtek: FakeDtek, mock_config_entry: MockConfigEntry
) -> None:
    """A missing house, no groups or DTEK down remove nothing."""
    fake_dtek.houses[HOUSE] = make_house([GROUP, OTHER])
    events = async_capture_events(hass, EVENT_BUS)
    await setup_entry(hass, mock_config_entry)
    # The first update is silent, the group was there from the start.
    assert bus_events(events) == []

    for change in range(3):
        if change == 0:
            del fake_dtek.houses[HOUSE]
        elif change == 1:
            fake_dtek.houses[HOUSE] = make_house([])
        else:
            fake_dtek.ajax_error = aiohttp.ClientConnectionError()
        for _ in range(3):
            await refresh(hass, mock_config_entry)
    data = mock_config_entry.runtime_data.data
    assert data.extra_groups == [OTHER]
    assert data.groups_at_address == [GROUP, OTHER]
    assert bus_events(events, "groups_changed") == []


@pytest.mark.parametrize("options", [COMBINED])
async def test_combined_groups(
    hass: HomeAssistant, fake_dtek: FakeDtek, mock_config_entry: MockConfigEntry
) -> None:
    """Combined, an outage of any group is an outage of the entry."""
    events = async_capture_events(hass, EVENT_BUS)
    await setup_entry(hass, mock_config_entry)

    fake_dtek.houses[HOUSE] = make_house([GROUP, OTHER])
    await refresh(hass, mock_config_entry)
    data = mock_config_entry.runtime_data.data
    assert data.combined
    # The past of today stays; from now on 4.2 (08-12) adds to 3.1.
    assert data.days[TODAY] == slots(("10:00", "14:00"), ("18:00", "20:30"))
    assert data.group_days[GROUP][TODAY] == slots(
        ("12:00", "14:00"), ("18:00", "20:30")
    )
    # 10:10 is now inside an outage of 4.2.
    assert [e["type"] for e in bus_events(events)] == [
        "groups_changed",
        "schedule_changed",
        "outage_started",
    ]
    assert bus_events(events, "schedule_changed")[0]["outages_text"] == (
        "10:00–14:00, 18:00–20:30"
    )
    assert (
        hass.states.get(get_entity_id(hass, "binary_sensor", "scheduled_outage")).state
        == "on"
    )

    # Without the other group the entry follows the main group again.
    fake_dtek.houses[HOUSE] = make_house([GROUP])
    for _ in range(3):
        await refresh(hass, mock_config_entry)
    data = mock_config_entry.runtime_data.data
    assert not data.combined
    assert data.days[TODAY] == slots(("12:00", "14:00"), ("18:00", "20:30"))
    assert bus_events(events, "schedule_changed")[-1]["outages_text"] == (
        "12:00–14:00, 18:00–20:30"
    )


@pytest.mark.parametrize("options", [COMBINED])
async def test_combined_from_the_start(
    hass: HomeAssistant, fake_dtek: FakeDtek, mock_config_entry: MockConfigEntry
) -> None:
    """The first update combines the groups listed for the house."""
    fake_dtek.houses[HOUSE] = make_house([GROUP, OTHER])
    fake_dtek.days[TOMORROW] = {GROUP: slots(("00:00", "01:00"))}
    fake_dtek.weekly[OTHER] = {
        day: slots(possible=(("06:00", "07:00"),)) for day in range(1, 8)
    }
    await setup_entry(hass, mock_config_entry)
    data = mock_config_entry.runtime_data.data
    assert data.days == {
        TODAY: slots(("08:00", "14:00"), ("18:00", "20:30")),
        # 4.2 has no tomorrow yet: 3.1 alone.
        TOMORROW: slots(("00:00", "01:00")),
    }
    assert data.preset[1] == slots(possible=(("06:00", "07:00"), ("16:00", "20:00")))


@pytest.mark.parametrize("options", [{**COMBINED, CONF_EXCLUDED_GROUPS: [OTHER]}])
async def test_excluded_group(
    hass: HomeAssistant, fake_dtek: FakeDtek, mock_config_entry: MockConfigEntry
) -> None:
    """A group left out in the options is not followed."""
    fake_dtek.houses[HOUSE] = make_house([GROUP, OTHER])
    await setup_entry(hass, mock_config_entry)
    data = mock_config_entry.runtime_data.data
    assert data.groups_at_address == [GROUP, OTHER]
    assert data.extra_groups == []
    assert data.days[TODAY] == slots(("12:00", "14:00"), ("18:00", "20:30"))


async def test_main_group_moves_to_other_group(
    hass: HomeAssistant, fake_dtek: FakeDtek, mock_config_entry: MockConfigEntry
) -> None:
    """The other group becoming the main one is a group change only."""
    fake_dtek.houses[HOUSE] = make_house([GROUP, OTHER])
    await setup_entry(hass, mock_config_entry)
    events = async_capture_events(hass, EVENT_BUS)

    fake_dtek.houses[HOUSE] = make_house([OTHER])
    await refresh(hass, mock_config_entry)
    data = mock_config_entry.runtime_data.data
    assert data.group == OTHER
    assert data.extra_groups == []
    assert set(data.group_days) == {OTHER}
    assert data.days[TODAY] == slots(("10:00", "12:00"))
    assert bus_events(events, "groups_changed") == []
    assert bus_events(events, "group_changed")[0]["previous_group"] == GROUP


async def test_store_without_other_groups(
    hass: HomeAssistant,
    fake_dtek: FakeDtek,
    mock_config_entry: MockConfigEntry,
    hass_storage: dict[str, Any],
) -> None:
    """A Store from before: its groups are followed, quietly, with a full schedule."""
    hass_storage[STORE_KEY] = store_payload(
        fact_update="18.10.2026 09:00",
        days={TODAY.isoformat(): slots(("12:00", "14:00"), ("18:00", "20:30"))},
        preset={"7": slots()},
        groups_at_address=[GROUP, OTHER],
    )
    fake_dtek.houses[HOUSE] = make_house([GROUP, OTHER])
    events = async_capture_events(hass, EVENT_BUS)
    await setup_entry(hass, mock_config_entry)

    assert fake_dtek.schedule_forms[0]["data[2][value]"] == FORCE_UPDATE_FACT
    data = mock_config_entry.runtime_data.data
    assert data.extra_groups == [OTHER]
    assert data.group_days[GROUP][TODAY] == data.days[TODAY]
    assert data.group_days[OTHER][TODAY] == slots(("08:00", "12:00"))
    assert bus_events(events) == []


@pytest.mark.parametrize("options", [COMBINED])
async def test_restart_with_combine_turned_on(
    hass: HomeAssistant,
    fake_dtek: FakeDtek,
    mock_config_entry: MockConfigEntry,
    hass_storage: dict[str, Any],
) -> None:
    """Turning combining on changes the schedule without announcing it."""
    group_days = {
        GROUP: {TODAY.isoformat(): slots(("12:00", "14:00"), ("18:00", "20:30"))},
        OTHER: {TODAY.isoformat(): slots(("08:00", "12:00"))},
    }
    hass_storage[STORE_KEY] = store_payload(
        fact_update="18.10.2026 09:00",
        days=group_days[GROUP],
        group_days=group_days,
        extra_groups=[OTHER],
        groups_at_address=[GROUP, OTHER],
    )
    fake_dtek.houses[HOUSE] = make_house([GROUP, OTHER])
    events = async_capture_events(hass, EVENT_BUS)
    await setup_entry(hass, mock_config_entry)

    assert fake_dtek.schedule_forms[0]["data[2][value]"] == "18.10.2026 09:00"
    assert mock_config_entry.runtime_data.data.days[TODAY] == slots(
        ("10:00", "14:00"), ("18:00", "20:30")
    )
    assert bus_events(events) == []


async def test_hidden_schedule_clears_other_groups(
    hass: HomeAssistant, fake_dtek: FakeDtek, mock_config_entry: MockConfigEntry
) -> None:
    """While DTEK hides the schedule, the other groups have none either."""
    fake_dtek.houses[HOUSE] = make_house([GROUP, OTHER])
    await setup_entry(hass, mock_config_entry)
    fake_dtek.flags["showTableFact"] = False
    await refresh(hass, mock_config_entry)
    data = mock_config_entry.runtime_data.data
    assert data.group_days[OTHER][TODAY] == slots(("08:00", "10:00"))
    assert data.group_days[GROUP][TODAY] == slots()


@pytest.mark.parametrize("entry_data", [GROUP_ONLY_DATA])
@pytest.mark.parametrize("options", [{**COMBINED, CONF_EXTRA_GROUPS: [OTHER, GROUP]}])
async def test_group_only_entry_with_other_groups(
    hass: HomeAssistant, fake_dtek: FakeDtek, mock_config_entry: MockConfigEntry
) -> None:
    """Without an address the other groups come from the options."""
    await setup_entry(hass, mock_config_entry)
    data = mock_config_entry.runtime_data.data
    assert data.extra_groups == [OTHER]
    assert data.days[TODAY] == slots(("08:00", "14:00"), ("18:00", "20:30"))


@pytest.mark.parametrize("options", [{**DEFAULT_OPTIONS, CONF_GROUPS_MODE: "all"}])
async def test_all_groups_mode(
    hass: HomeAssistant, fake_dtek: FakeDtek, mock_config_entry: MockConfigEntry
) -> None:
    """An outage of every group is an outage, of some of them a possible one."""
    fake_dtek.houses[HOUSE] = make_house([GROUP, OTHER])
    fake_dtek.days[TODAY][OTHER] = slots(("08:00", "13:00"))
    fake_dtek.days[TOMORROW] = {GROUP: slots(("00:00", "01:00"))}
    await setup_entry(hass, mock_config_entry)
    data = mock_config_entry.runtime_data.data
    assert data.groups_mode == "all"
    assert data.combined
    assert data.days[TODAY] == slots(
        ("12:00", "13:00"),
        possible=(("08:00", "12:00"), ("13:00", "14:00"), ("18:00", "20:30")),
    )
    # 4.2 has no tomorrow yet: an outage of 3.1 alone is only possible.
    assert data.days[TOMORROW] == slots(possible=(("00:00", "01:00"),))
    assert [(i.start, i.end) for i in data.outages] == [
        (kyiv(TODAY, "12:00"), kyiv(TODAY, "13:00"))
    ]


async def test_whole_schedule_not_asked_twice(
    hass: HomeAssistant, fake_dtek: FakeDtek, mock_config_entry: MockConfigEntry
) -> None:
    """A request that asked for the whole schedule in vain is not repeated."""
    await setup_entry(hass, mock_config_entry)
    fake_dtek.houses[HOUSE] = make_house([GROUP, OTHER])
    fake_dtek.send_fact = False

    # The known version first; the new group then asks for the whole one.
    sent = len(fake_dtek.schedule_forms)
    await refresh(hass, mock_config_entry)
    assert [f["data[2][value]"] for f in fake_dtek.schedule_forms[sent:]] == [
        "18.10.2026 09:00",
        FORCE_UPDATE_FACT,
    ]
    # Still no schedule: one request for the whole one, not two.
    sent = len(fake_dtek.schedule_forms)
    await refresh(hass, mock_config_entry)
    assert [f["data[2][value]"] for f in fake_dtek.schedule_forms[sent:]] == [
        FORCE_UPDATE_FACT
    ]

    fake_dtek.send_fact = True
    await refresh(hass, mock_config_entry)
    data = mock_config_entry.runtime_data.data
    assert data.group_days[OTHER] == {TODAY: slots(("08:00", "12:00"))}


@pytest.mark.parametrize(
    "options", [{**DEFAULT_OPTIONS, CONF_EXCLUDED_GROUPS: [OTHER]}]
)
async def test_group_no_longer_excluded(
    hass: HomeAssistant, fake_dtek: FakeDtek, mock_config_entry: MockConfigEntry
) -> None:
    """A group taken out of the left-out ones is back at once, with no event."""
    fake_dtek.houses[HOUSE] = make_house([GROUP, OTHER])
    await setup_entry(hass, mock_config_entry)
    assert mock_config_entry.runtime_data.data.extra_groups == []

    # Even with DTEK down: the groups it listed are in the Store.
    fake_dtek.ajax_error = aiohttp.ClientConnectionError()
    events = async_capture_events(hass, EVENT_BUS)
    hass.config_entries.async_update_entry(
        mock_config_entry, options={**DEFAULT_OPTIONS, CONF_EXCLUDED_GROUPS: []}
    )
    await hass.config_entries.async_reload(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    data = mock_config_entry.runtime_data.data
    assert data.extra_groups == [OTHER]
    # The mirror has the same version; the new group takes it.
    assert data.group_days[OTHER] == {TODAY: slots(("08:00", "12:00"))}
    assert bus_events(events, "groups_changed") == []
