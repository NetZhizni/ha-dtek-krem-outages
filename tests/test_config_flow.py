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
    match_settlement,
    match_street,
    settlement_sort_key,
    street_choices,
)
from custom_components.dtek_krem_outages.const import (
    CONF_GROUP,
    CONF_GROUP_MANUAL,
    CONF_HOUSE,
    CONF_LANGUAGE,
    CONF_SETTLEMENT,
    CONF_SHOW_POSSIBLE,
    CONF_STREET,
    CONF_UPDATE_INTERVAL,
    CONF_USE_MIRROR,
    CONF_WARN_END,
    CONF_WARN_START,
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


def fields_of(result: dict[str, Any]) -> list[str]:
    """Return the field names of a form."""
    return [str(marker) for marker in result["data_schema"].schema]


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


def test_other_spellings() -> None:
    """Settlements with the same name share their streets."""
    streets = {
        "с. Софіївська Борщагівка": ["вул. Миру", "пров. Миру", "вул. Сонячна"],
        "Софіївська Борщагівка": ["Без вулиці", "вул. Сонячна"],
        "с. Петропавлівська Борщагівка": ["вул. Миру"],
    }
    assert match_settlement("Софіївська Борщагівка", streets) == (
        "Софіївська Борщагівка"
    )
    assert match_settlement(" софіївська  борщагівка", streets) == (
        "Софіївська Борщагівка"
    )
    assert match_settlement("смт Софіївська Борщагівка", streets) == (
        "с. Софіївська Борщагівка"
    )
    assert match_settlement("Київ", streets) is None
    assert match_settlement(None, streets) is None

    choices = street_choices(streets, "Софіївська Борщагівка")
    assert choices == {
        "Без вулиці": ("Софіївська Борщагівка", "Без вулиці"),
        "вул. Сонячна": ("Софіївська Борщагівка", "вул. Сонячна"),
        "вул. Миру (с. Софіївська Борщагівка)": (
            "с. Софіївська Борщагівка",
            "вул. Миру",
        ),
        "пров. Миру (с. Софіївська Борщагівка)": (
            "с. Софіївська Борщагівка",
            "пров. Миру",
        ),
        "вул. Сонячна (с. Софіївська Борщагівка)": (
            "с. Софіївська Борщагівка",
            "вул. Сонячна",
        ),
    }
    assert street_choices(streets, "м. Київ") == {}
    # The own street wins over the one of another spelling.
    assert match_street("Сонячна", choices) == "вул. Сонячна"
    assert match_street("вулиця сонячна", choices) == "вул. Сонячна"
    # Two streets of another spelling fit: ambiguous.
    assert match_street("миру", choices) is None
    assert match_street("пров. миру", choices) == (
        "пров. Миру (с. Софіївська Борщагівка)"
    )
    own = street_choices(streets, "с. Софіївська Борщагівка")
    assert match_street("без вулиці", own) == "Без вулиці (Софіївська Борщагівка)"
    assert match_street("вул.", own) is None
    assert match_street("Нова", own) is None
    assert match_street(None, own) is None


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
    assert [o["value"] for o in options_of(result, CONF_LANGUAGE)] == [
        "uk",
        "en",
        "ru",
    ]

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
    assert result["options"][CONF_LANGUAGE] == "uk"
    assert result["result"].unique_id == f"{SETTLEMENT}|{STREET}|{HOUSE}"


async def test_language_on_creation(hass: HomeAssistant, fake_dtek: FakeDtek) -> None:
    """The language chosen with the house goes to the options."""
    result = await start(hass)
    result = await submit(hass, result, {CONF_SETTLEMENT: SETTLEMENT})
    result = await submit(hass, result, {CONF_STREET: STREET})
    result = await submit(hass, result, {CONF_HOUSE: HOUSE, CONF_LANGUAGE: "en"})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["options"] == {**DEFAULT_OPTIONS, CONF_LANGUAGE: "en"}


async def test_street_of_other_spelling(
    hass: HomeAssistant, fake_dtek: FakeDtek
) -> None:
    """A street listed under another spelling keeps the settlement that has it."""
    fake_dtek.streets = {
        "с. Софіївська Борщагівка": ["вул. Миру", "вул. Жулянська"],
        "Софіївська Борщагівка": ["Без вулиці"],
    }
    result = await start(hass)
    assert options_of(result, CONF_SETTLEMENT) == [
        "Софіївська Борщагівка",
        "с. Софіївська Борщагівка",
    ]
    result = await submit(hass, result, {CONF_SETTLEMENT: "Софіївська Борщагівка"})
    assert result["step_id"] == "street"
    assert options_of(result, CONF_STREET) == [
        "Без вулиці",
        "вул. Жулянська (с. Софіївська Борщагівка)",
        "вул. Миру (с. Софіївська Борщагівка)",
    ]
    result = await submit(hass, result, {CONF_STREET: "миру"})
    assert result["step_id"] == "house"
    assert result["description_placeholders"]["settlement"] == (
        "с. Софіївська Борщагівка"
    )
    result = await submit(hass, result, {CONF_HOUSE: HOUSE})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == f"с. Софіївська Борщагівка, вул. Миру, {HOUSE}"
    assert result["data"][CONF_SETTLEMENT] == "с. Софіївська Борщагівка"
    assert result["data"][CONF_STREET] == "вул. Миру"


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
            CONF_WARN_START: ["60", "5"],
            CONF_WARN_END: ["30"],
            CONF_USE_MIRROR: False,
            CONF_SHOW_POSSIBLE: False,
            CONF_LANGUAGE: "en",
        },
    )
    await hass.async_block_till_done()
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert mock_config_entry.options == {
        CONF_UPDATE_INTERVAL: 10,
        CONF_WARN_START: [60, 5],
        CONF_WARN_END: [30],
        CONF_USE_MIRROR: False,
        CONF_SHOW_POSSIBLE: False,
        CONF_LANGUAGE: "en",
    }
    coordinator = mock_config_entry.runtime_data
    assert coordinator is not old_coordinator
    assert coordinator.update_interval == timedelta(minutes=10)
    assert coordinator.warn_start == (timedelta(minutes=60), timedelta(minutes=5))
    assert coordinator.warn_end == (timedelta(minutes=30),)
    assert not coordinator.use_mirror
    assert coordinator.language == "en"


async def test_reconfigure(
    hass: HomeAssistant, fake_dtek: FakeDtek, mock_config_entry: MockConfigEntry
) -> None:
    """Reconfigure suggests the current address and moves the entry."""
    await setup_entry(hass, mock_config_entry)
    result = await mock_config_entry.start_reconfigure_flow(hass)
    assert result["step_id"] == "user"
    result = await submit(hass, result, {CONF_SETTLEMENT: SETTLEMENT})
    result = await submit(hass, result, {CONF_STREET: STREET})
    # The language is an option; reconfiguring changes only the address.
    assert CONF_LANGUAGE not in fields_of(result)
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
