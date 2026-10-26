"""Tests for updates, merging, storage and change events."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

import aiohttp
from freezegun.api import FrozenDateTimeFactory
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_capture_events,
    async_fire_time_changed,
)

from custom_components.dtek_krem_outages.const import (
    CONF_GROUP,
    CONF_USE_MIRROR,
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
