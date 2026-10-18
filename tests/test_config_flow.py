"""Tests for the config, options and reconfigure flows."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

import aiohttp
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.dtek_krem_outages.config_flow import (
    build_title,
    house_sort_key,
    match_choice,
    settlement_sort_key,
)
from custom_components.dtek_krem_outages.const import (
    CONF_GROUP,
    CONF_GROUP_MANUAL,
    CONF_HOUSE,
    CONF_SETTLEMENT,
    CONF_SHOW_POSSIBLE,
    CONF_STREET,
    CONF_UPDATE_INTERVAL,
    CONF_USE_MIRROR,
    CONF_WARNING_MINUTES,
    DEFAULT_OPTIONS,
    DOMAIN,
)
from homeassistant.config_entries import SOURCE_USER
from homeassistant.const import CONF_NAME
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType

from .conftest import GROUP, HOUSE, SETTLEMENT, STREET, TITLE, FakeDtek, setup_entry


async def start(hass: HomeAssistant) -> dict[str, Any]:
    """Start a user flow."""
    return await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )


async def submit(hass: HomeAssistant, result: dict[str, Any], data: dict) -> dict:
    """Submit a step."""
    result = await hass.config_entries.flow.async_configure(result["flow_id"], data)
    await hass.async_block_till_done()
    return result


def options_of(result: dict[str, Any], key: str) -> list[Any]:
    """Return the selector options of a form field."""
    for marker, selector in result["data_schema"].schema.items():
        if marker == key:
            return selector.config["options"]
    raise KeyError(key)


def test_helpers() -> None:
    """Sorting follows the Ukrainian alphabet, matching ignores case."""
    names = ["с. Яблунівка", "м. Ірпінь", "с. Їжакевичі", "смт Гостомель", "с. Ґудзь"]
    assert sorted(names, key=settlement_sort_key) == [
        "смт Гостомель",
        "с. Ґудзь",
        "м. Ірпінь",
        "с. Їжакевичі",
        "с. Яблунівка",
    ]
    houses = ["10", "2", "10/2", "10 а", "-", "1"]
    assert sorted(houses, key=house_sort_key) == ["1", "2", "10", "10 а", "10/2", "-"]
    assert match_choice("  м.  бориспіль ", [SETTLEMENT]) == SETTLEMENT
    assert match_choice("Київ", [SETTLEMENT]) is None
    assert match_choice(None, [SETTLEMENT]) is None
    assert build_title("с. Буча", "Без вулиці", "5") == "с. Буча, 5"


async def test_full_flow(hass: HomeAssistant, fake_dtek: FakeDtek) -> None:
    """Settlement, street and a house with one group create the entry."""
    result = await start(hass)
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "user"
    assert options_of(result, CONF_SETTLEMENT) == ["м. Бориспіль", "с. Буча"]

    result = await submit(hass, result, {CONF_SETTLEMENT: "м. бориспіль"})
    assert result["step_id"] == "street"
    assert options_of(result, CONF_STREET) == ["вул. Київський Шлях", STREET]

    result = await submit(hass, result, {CONF_STREET: STREET})
    assert result["step_id"] == "house"
    assert options_of(result, CONF_HOUSE) == ["2", "8 а", "10", "43"]

    result = await submit(hass, result, {CONF_HOUSE: HOUSE})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == TITLE
    assert result["data"] == {
        CONF_SETTLEMENT: SETTLEMENT,
        CONF_STREET: STREET,
        CONF_HOUSE: HOUSE,
        CONF_GROUP: GROUP,
        CONF_GROUP_MANUAL: False,
    }
    assert result["options"] == DEFAULT_OPTIONS
    assert result["result"].unique_id == f"{SETTLEMENT}|{STREET}|{HOUSE}"


async def test_house_with_several_groups(
    hass: HomeAssistant, fake_dtek: FakeDtek
) -> None:
    """Several groups: the user picks one of them; a name is kept."""
    result = await start(hass)
    result = await submit(hass, result, {CONF_SETTLEMENT: SETTLEMENT})
    result = await submit(hass, result, {CONF_STREET: STREET})
    result = await submit(hass, result, {CONF_HOUSE: "8 а", CONF_NAME: " Дача "})
    assert result["step_id"] == "group"
    assert result["description_placeholders"]["groups"] == "3.1, 4.2"
    assert [o["value"] for o in options_of(result, CONF_GROUP)] == [
        "GPV3.1",
        "GPV4.2",
    ]
    result = await submit(hass, result, {CONF_GROUP: "GPV4.2"})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "Дача"
    assert result["data"][CONF_GROUP] == "GPV4.2"
    assert result["data"][CONF_GROUP_MANUAL] is True


async def test_house_without_group(hass: HomeAssistant, fake_dtek: FakeDtek) -> None:
    """No group: every group is offered."""
    result = await start(hass)
    result = await submit(hass, result, {CONF_SETTLEMENT: SETTLEMENT})
    result = await submit(hass, result, {CONF_STREET: STREET})
    result = await submit(hass, result, {CONF_HOUSE: "10"})
    assert result["step_id"] == "group"
    assert result["description_placeholders"]["groups"] == "—"
    assert len(options_of(result, CONF_GROUP)) == 12


async def test_unknown_values(hass: HomeAssistant, fake_dtek: FakeDtek) -> None:
    """Typed values that are not in the lists are rejected."""
    result = await start(hass)
    result = await submit(hass, result, {CONF_SETTLEMENT: "м. Київ"})
    assert result["errors"] == {CONF_SETTLEMENT: "unknown_settlement"}
    result = await submit(hass, result, {CONF_SETTLEMENT: SETTLEMENT})
    result = await submit(hass, result, {CONF_STREET: "вул. Нова"})
    assert result["errors"] == {CONF_STREET: "unknown_street"}
    result = await submit(hass, result, {CONF_STREET: STREET})
    result = await submit(hass, result, {CONF_HOUSE: "999"})
    assert result["errors"] == {CONF_HOUSE: "unknown_house"}


async def test_cannot_connect_then_recovers(
    hass: HomeAssistant, fake_dtek: FakeDtek
) -> None:
    """Connection errors show an error; submitting again retries."""
    fake_dtek.ajax_error = aiohttp.ClientConnectionError()
    result = await start(hass)
    assert result["errors"] == {"base": "cannot_connect"}
    fake_dtek.ajax_error = None
    result = await submit(hass, result, {})
    assert result["step_id"] == "user"
    assert not result["errors"]
    result = await submit(hass, result, {CONF_SETTLEMENT: SETTLEMENT})

    fake_dtek.ajax_error = TimeoutError()
    result = await submit(hass, result, {CONF_STREET: STREET})
    assert result["step_id"] == "house"
    assert result["errors"] == {"base": "cannot_connect"}
    fake_dtek.ajax_error = None
    result = await submit(hass, result, {})
    assert result["step_id"] == "house"
    assert not result["errors"]


async def test_street_without_houses(hass: HomeAssistant, fake_dtek: FakeDtek) -> None:
    """A street DTEK knows nothing about shows an error."""
    fake_dtek.houses = {}
    result = await start(hass)
    result = await submit(hass, result, {CONF_SETTLEMENT: SETTLEMENT})
    result = await submit(hass, result, {CONF_STREET: STREET})
    assert result["errors"] == {"base": "no_houses"}


async def test_duplicate(
    hass: HomeAssistant, fake_dtek: FakeDtek, mock_config_entry: MockConfigEntry
) -> None:
    """The same address can't be added twice."""
    mock_config_entry.add_to_hass(hass)
    result = await start(hass)
    result = await submit(hass, result, {CONF_SETTLEMENT: SETTLEMENT})
    result = await submit(hass, result, {CONF_STREET: STREET})
    result = await submit(hass, result, {CONF_HOUSE: HOUSE})
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"


async def test_options_flow_reloads(
    hass: HomeAssistant, fake_dtek: FakeDtek, mock_config_entry: MockConfigEntry
) -> None:
    """Saving options updates the entry and reloads it."""
    await setup_entry(hass, mock_config_entry)
    old_coordinator = mock_config_entry.runtime_data

    result = await hass.config_entries.options.async_init(mock_config_entry.entry_id)
    assert result["type"] is FlowResultType.FORM
    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {
            CONF_UPDATE_INTERVAL: 10,
            CONF_WARNING_MINUTES: 60,
            CONF_USE_MIRROR: False,
            CONF_SHOW_POSSIBLE: False,
        },
    )
    await hass.async_block_till_done()
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert mock_config_entry.options == {
        CONF_UPDATE_INTERVAL: 10,
        CONF_WARNING_MINUTES: 60,
        CONF_USE_MIRROR: False,
        CONF_SHOW_POSSIBLE: False,
    }
    coordinator = mock_config_entry.runtime_data
    assert coordinator is not old_coordinator
    assert coordinator.update_interval == timedelta(minutes=10)
    assert coordinator.warning == timedelta(minutes=60)
    assert not coordinator.use_mirror


async def test_reconfigure(
    hass: HomeAssistant, fake_dtek: FakeDtek, mock_config_entry: MockConfigEntry
) -> None:
    """Reconfigure suggests the current address and moves the entry."""
    await setup_entry(hass, mock_config_entry)
    result = await mock_config_entry.start_reconfigure_flow(hass)
    assert result["step_id"] == "user"
    result = await submit(hass, result, {CONF_SETTLEMENT: SETTLEMENT})
    result = await submit(hass, result, {CONF_STREET: STREET})
    result = await submit(hass, result, {CONF_HOUSE: "2"})
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reconfigure_successful"
    assert mock_config_entry.data[CONF_HOUSE] == "2"
    assert mock_config_entry.title == f"{SETTLEMENT}, {STREET}, 2"
    assert mock_config_entry.unique_id == f"{SETTLEMENT}|{STREET}|2"
    assert mock_config_entry.runtime_data.house == "2"


async def test_reconfigure_duplicate(
    hass: HomeAssistant, fake_dtek: FakeDtek, mock_config_entry: MockConfigEntry
) -> None:
    """Moving onto the address of another entry is rejected."""
    MockConfigEntry(
        domain=DOMAIN,
        unique_id=f"{SETTLEMENT}|{STREET}|2",
        data={
            CONF_SETTLEMENT: SETTLEMENT,
            CONF_STREET: STREET,
            CONF_HOUSE: "2",
            CONF_GROUP: GROUP,
        },
    ).add_to_hass(hass)
    mock_config_entry.add_to_hass(hass)
    result = await mock_config_entry.start_reconfigure_flow(hass)
    result = await submit(hass, result, {CONF_SETTLEMENT: SETTLEMENT})
    result = await submit(hass, result, {CONF_STREET: STREET})
    result = await submit(hass, result, {CONF_HOUSE: "2"})
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"
    assert mock_config_entry.data[CONF_HOUSE] == HOUSE
