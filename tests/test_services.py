"""Tests for the services and diagnostics."""

from __future__ import annotations

import aiohttp
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.dtek_krem_outages.const import ATTR_CONFIG_ENTRY_ID, DOMAIN
from custom_components.dtek_krem_outages.diagnostics import (
    async_get_config_entry_diagnostics,
)
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError

from .conftest import ENTRY_ID, GROUP, TODAY, TOMORROW, FakeDtek, setup_entry, slots


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
    hass: HomeAssistant, fake_dtek: FakeDtek, mock_config_entry: MockConfigEntry
) -> None:
    """Refresh fetches again and reports when no source answered."""
    await setup_entry(hass, mock_config_entry)
    count = len(fake_dtek.schedule_forms)
    await hass.services.async_call(DOMAIN, "refresh", {}, blocking=True)
    assert len(fake_dtek.schedule_forms) == count + 1

    fake_dtek.ajax_error = aiohttp.ClientConnectionError()
    # The mirror still answers: that is not a failure.
    await hass.services.async_call(DOMAIN, "refresh", {}, blocking=True)
    fake_dtek.mirror_error = aiohttp.ClientConnectionError()
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
