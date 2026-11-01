"""Tests for the services and diagnostics."""

from __future__ import annotations

from datetime import timedelta

import aiohttp
from freezegun.api import FrozenDateTimeFactory
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.dtek_krem_outages.const import (
    ATTR_CONFIG_ENTRY_ID,
    DOMAIN,
    REFRESH_COOLDOWN,
)
from custom_components.dtek_krem_outages.diagnostics import (
    async_get_config_entry_diagnostics,
)
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError

from .conftest import (
    ENTRY_ID,
    GROUP,
    HOUSE,
    TODAY,
    TOMORROW,
    FakeDtek,
    make_house,
    setup_entry,
    slots,
)


async def test_get_schedule(
    hass: HomeAssistant, fake_dtek: FakeDtek, mock_config_entry: MockConfigEntry
) -> None:
    """The response holds the stored days and the weekly schedule."""
    fake_dtek.days[TOMORROW] = {GROUP: slots(("06:00", "07:00"))}
    await setup_entry(hass, mock_config_entry)

    for data in ({}, {ATTR_CONFIG_ENTRY_ID: ENTRY_ID}):
        response = await hass.services.async_call(
            DOMAIN, "get_schedule", data, blocking=True, return_response=True
        )
        assert len(response["entries"]) == 1
        entry = response["entries"][0]
        assert entry["config_entry_id"] == ENTRY_ID
        assert entry["group"] == GROUP
        assert entry["group_name"] == "3.1"
        assert entry["source"] == "dtek"
        assert entry["schedule_updated"] == "2026-10-18T09:00:00+03:00"
        today = entry["days"][TODAY.isoformat()]
        assert today["outages_text"] == "12:00–14:00, 18:00–20:30"
        assert today["outage_minutes"] == 270
        assert today["outages"][0] == {
            "start": "2026-10-18T12:00:00+03:00",
            "end": "2026-10-18T14:00:00+03:00",
        }
        assert entry["days"][TOMORROW.isoformat()]["outages_text"] == "06:00–07:00"
        assert sorted(entry["weekly"]) == ["1", "2", "3", "4", "5", "6", "7"]
        assert entry["address_outage"] is None


async def test_refresh(
    hass: HomeAssistant,
    fake_dtek: FakeDtek,
    mock_config_entry: MockConfigEntry,
    frozen_now: FrozenDateTimeFactory,
) -> None:
    """Refresh fetches again and reports when no source answered."""
    await setup_entry(hass, mock_config_entry)
    count = len(fake_dtek.schedule_forms)
    frozen_now.tick(timedelta(seconds=REFRESH_COOLDOWN))
    await hass.services.async_call(DOMAIN, "refresh", {}, blocking=True)
    assert len(fake_dtek.schedule_forms) == count + 1

    fake_dtek.ajax_error = aiohttp.ClientConnectionError()
    # The mirror still answers: that is not a failure.
    frozen_now.tick(timedelta(seconds=REFRESH_COOLDOWN))
    await hass.services.async_call(DOMAIN, "refresh", {}, blocking=True)
    fake_dtek.mirror_error = aiohttp.ClientConnectionError()
    frozen_now.tick(timedelta(seconds=REFRESH_COOLDOWN))
    with pytest.raises(HomeAssistantError):
        await hass.services.async_call(DOMAIN, "refresh", {}, blocking=True)


async def test_refresh_cooldown(
    hass: HomeAssistant,
    fake_dtek: FakeDtek,
    mock_config_entry: MockConfigEntry,
    frozen_now: FrozenDateTimeFactory,
) -> None:
    """Calls within a minute of the last update don't ask DTEK again."""
    await setup_entry(hass, mock_config_entry)
    count = len(fake_dtek.schedule_forms)
    for _ in range(5):
        await hass.services.async_call(DOMAIN, "refresh", {}, blocking=True)
    assert len(fake_dtek.schedule_forms) == count

    frozen_now.tick(timedelta(seconds=REFRESH_COOLDOWN - 1))
    await hass.services.async_call(DOMAIN, "refresh", {}, blocking=True)
    assert len(fake_dtek.schedule_forms) == count
    frozen_now.tick(timedelta(seconds=1))
    await hass.services.async_call(DOMAIN, "refresh", {}, blocking=True)
    assert len(fake_dtek.schedule_forms) == count + 1

    # A failed update is reported again while it is the last one.
    fake_dtek.ajax_error = aiohttp.ClientConnectionError()
    fake_dtek.mirror_error = aiohttp.ClientConnectionError()
    frozen_now.tick(timedelta(seconds=REFRESH_COOLDOWN))
    with pytest.raises(HomeAssistantError):
        await hass.services.async_call(DOMAIN, "refresh", {}, blocking=True)
    with pytest.raises(HomeAssistantError):
        await hass.services.async_call(DOMAIN, "refresh", {}, blocking=True)


async def test_service_errors(
    hass: HomeAssistant, fake_dtek: FakeDtek, mock_config_entry: MockConfigEntry
) -> None:
    """Unknown, unloaded or missing entries are reported."""
    await setup_entry(hass, mock_config_entry)
    with pytest.raises(ServiceValidationError):
        await hass.services.async_call(
            DOMAIN,
            "get_schedule",
            {ATTR_CONFIG_ENTRY_ID: "missing"},
            blocking=True,
            return_response=True,
        )
    await hass.config_entries.async_unload(mock_config_entry.entry_id)
    with pytest.raises(ServiceValidationError):
        await hass.services.async_call(
            DOMAIN,
            "refresh",
            {ATTR_CONFIG_ENTRY_ID: ENTRY_ID},
            blocking=True,
        )
    with pytest.raises(ServiceValidationError):
        await hass.services.async_call(DOMAIN, "refresh", {}, blocking=True)


async def test_diagnostics(
    hass: HomeAssistant, fake_dtek: FakeDtek, mock_config_entry: MockConfigEntry
) -> None:
    """The street and house are redacted."""
    await setup_entry(hass, mock_config_entry)
    result = await async_get_config_entry_diagnostics(hass, mock_config_entry)
    assert result["entry"]["data"]["street"] == "**REDACTED**"
    assert result["entry"]["data"]["house"] == "**REDACTED**"
    assert result["entry"]["title"] == "**REDACTED**"
    assert result["entry"]["data"]["group"] == GROUP
    assert result["state"]["street"] == "**REDACTED**"
    assert result["state"]["days"][TODAY.isoformat()]["outage_minutes"] == 270
    coordinator = result["coordinator"]
    assert coordinator["group_manual"] is False
    assert coordinator["missing_groups"] == {}
    assert coordinator["main_missing"] == 0
    assert coordinator["group_suggestions"] == []
    assert coordinator["full_fact_needed"] is False
    assert coordinator["other_days"] == {}


async def test_diagnostics_of_groups(
    hass: HomeAssistant, fake_dtek: FakeDtek, mock_config_entry: MockConfigEntry
) -> None:
    """The counters of the groups and the other groups calendar are shown."""
    fake_dtek.houses[HOUSE] = make_house([GROUP, "GPV4.2"])
    await setup_entry(hass, mock_config_entry)
    fake_dtek.houses[HOUSE] = make_house(["GPV4.2"])
    await mock_config_entry.runtime_data.async_refresh()
    result = await async_get_config_entry_diagnostics(hass, mock_config_entry)
    coordinator = result["coordinator"]
    assert coordinator["missing_groups"] == {}
    assert coordinator["main_missing"] == 1
    assert coordinator["group_suggestions"] == []
    assert coordinator["other_days"] == {
        "GPV4.2": {TODAY.isoformat(): slots(("08:00", "12:00"))}
    }


async def test_get_schedule_other_groups(
    hass: HomeAssistant, fake_dtek: FakeDtek, mock_config_entry: MockConfigEntry
) -> None:
    """Every followed group is in the response with its own schedule."""
    fake_dtek.houses[HOUSE] = make_house([GROUP, "GPV4.2"])
    await setup_entry(hass, mock_config_entry)
    response = await hass.services.async_call(
        DOMAIN, "get_schedule", {}, blocking=True, return_response=True
    )
    entry = response["entries"][0]
    assert entry["groups_at_address"] == [GROUP, "GPV4.2"]
    assert entry["extra_groups"] == ["GPV4.2"]
    assert entry["groups_mode"] == "main"
    assert list(entry["groups"]) == [GROUP, "GPV4.2"]
    other = entry["groups"]["GPV4.2"]
    assert other["group_name"] == "4.2"
    assert other["days"][TODAY.isoformat()]["outages_text"] == "08:00–12:00"
    assert sorted(other["weekly"]) == ["1", "2", "3", "4", "5", "6", "7"]
    main = entry["groups"][GROUP]["days"][TODAY.isoformat()]
    assert main == entry["days"][TODAY.isoformat()]
