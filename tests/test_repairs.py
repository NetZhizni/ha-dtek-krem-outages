"""Tests for the Repairs issue offering another main group."""

from __future__ import annotations

from http import HTTPStatus
from typing import Any

import aiohttp
import pytest
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_capture_events,
)
from pytest_homeassistant_custom_component.typing import ClientSessionGenerator

from custom_components.dtek_krem_outages.const import (
    CONF_EXCLUDED_GROUPS,
    CONF_GROUP,
    CONF_GROUP_MANUAL,
    DEFAULT_OPTIONS,
    DOMAIN,
    EVENT_BUS,
    FORCE_UPDATE_FACT,
    GROUP_REMOVAL_UPDATES,
    group_issue_id,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers import issue_registry as ir
from homeassistant.setup import async_setup_component

from .conftest import (
    ENTRY_ID,
    GROUP,
    HOUSE,
    TITLE,
    TODAY,
    FakeDtek,
    make_house,
    setup_entry,
    slots,
)
from .test_coordinator import STABILIZATION_OUTAGE, bus_events, refresh, stored

OTHER = "GPV4.2"
ISSUE_ID = group_issue_id(ENTRY_ID)


def issue(hass: HomeAssistant) -> ir.IssueEntry | None:
    """Return the issue of the test entry, None without one."""
    return ir.async_get(hass).async_get_issue(DOMAIN, ISSUE_ID)


async def answer(
    hass: HomeAssistant,
    fake_dtek: FakeDtek,
    entry: MockConfigEntry,
    groups: list[str],
    times: int = GROUP_REMOVAL_UPDATES,
    **outage: str,
) -> None:
    """Let DTEK list ``groups`` for the house in ``times`` answers."""
    fake_dtek.houses[HOUSE] = make_house(groups, **outage)
    for _ in range(times):
        await refresh(hass, entry)


async def start_fix(
    hass: HomeAssistant, hass_client: ClientSessionGenerator
) -> tuple[Any, dict[str, Any]]:
    """Open the fix flow the way the frontend does."""
    assert await async_setup_component(hass, "repairs", {})
    client = await hass_client()
    response = await client.post(
        "/api/repairs/issues/fix", json={"handler": DOMAIN, "issue_id": ISSUE_ID}
    )
    assert response.status == HTTPStatus.OK, await response.text()
    return client, await response.json()


async def submit_fix(client: Any, flow_id: str, data: dict[str, Any]) -> dict:
    """Send the form of the fix flow."""
    response = await client.post(f"/api/repairs/issues/fix/{flow_id}", json=data)
    assert response.status == HTTPStatus.OK, await response.text()
    return await response.json()


async def test_issue_after_answers_without_main_group(
    hass: HomeAssistant, fake_dtek: FakeDtek, mock_config_entry: MockConfigEntry
) -> None:
    """Three answers in a row without the main group raise the issue."""
    await setup_entry(hass, mock_config_entry)
    events = async_capture_events(hass, EVENT_BUS)
    await answer(hass, fake_dtek, mock_config_entry, [OTHER], GROUP_REMOVAL_UPDATES - 1)
    assert issue(hass) is None

    await answer(hass, fake_dtek, mock_config_entry, [OTHER], 1)
    found = issue(hass)
    assert found is not None
    assert found.is_fixable
    assert not found.is_persistent
    assert found.severity is ir.IssueSeverity.WARNING
    assert found.translation_key == "group_not_listed"
    assert found.translation_placeholders == {
        "title": TITLE,
        "group": "3.1",
        "groups": "4.2",
    }
    assert found.data == {"entry_id": ENTRY_ID}
    # Nothing moves by itself.
    assert mock_config_entry.runtime_data.data.group == GROUP
    assert bus_events(events, "group_changed") == []

    # DTEK lists the main group again: the issue goes away by itself.
    await answer(hass, fake_dtek, mock_config_entry, [GROUP, OTHER], 1)
    assert issue(hass) is None


async def test_stabilization_outage_does_not_count(
    hass: HomeAssistant, fake_dtek: FakeDtek, mock_config_entry: MockConfigEntry
) -> None:
    """The short list of a stabilization outage neither counts nor resets."""
    fake_dtek.houses[HOUSE] = make_house([GROUP, OTHER])
    await setup_entry(hass, mock_config_entry)
    await answer(hass, fake_dtek, mock_config_entry, [OTHER], GROUP_REMOVAL_UPDATES - 1)
    await answer(hass, fake_dtek, mock_config_entry, [OTHER], 3, **STABILIZATION_OUTAGE)
    assert issue(hass) is None

    await answer(hass, fake_dtek, mock_config_entry, [OTHER], 1)
    assert issue(hass) is not None
    # During an outage of the main group DTEK lists it: that settles it.
    await answer(hass, fake_dtek, mock_config_entry, [GROUP], 1, **STABILIZATION_OUTAGE)
    assert issue(hass) is None


@pytest.mark.parametrize(
    "options", [{**DEFAULT_OPTIONS, CONF_EXCLUDED_GROUPS: [OTHER]}]
)
async def test_left_out_group_not_offered(
    hass: HomeAssistant, fake_dtek: FakeDtek, mock_config_entry: MockConfigEntry
) -> None:
    """A group left out in the options is never offered as the main one."""
    await setup_entry(hass, mock_config_entry)
    await answer(hass, fake_dtek, mock_config_entry, [OTHER])
    assert issue(hass) is None

    await answer(hass, fake_dtek, mock_config_entry, [OTHER, "GPV5.1"], 1)
    assert issue(hass).translation_placeholders["groups"] == "5.1"


async def test_issue_for_a_chosen_group(
    hass: HomeAssistant,
    fake_dtek: FakeDtek,
    mock_config_entry: MockConfigEntry,
    entry_data: dict[str, Any],
) -> None:
    """A group the user chose gets the offer too: DTEK may have moved the house."""
    mock_config_entry.add_to_hass(hass)
    hass.config_entries.async_update_entry(
        mock_config_entry, data={**entry_data, CONF_GROUP_MANUAL: True}
    )
    await setup_entry(hass, mock_config_entry)
    await answer(hass, fake_dtek, mock_config_entry, [OTHER, "GPV5.1"])
    assert issue(hass).translation_placeholders["groups"] == "4.2, 5.1"


async def test_fix_flow_changes_the_main_group(
    hass: HomeAssistant,
    hass_client: ClientSessionGenerator,
    fake_dtek: FakeDtek,
    mock_config_entry: MockConfigEntry,
) -> None:
    """The fix flow takes the group chosen of those DTEK lists."""
    await setup_entry(hass, mock_config_entry)
    await answer(hass, fake_dtek, mock_config_entry, [OTHER, "GPV5.1"])
    events = async_capture_events(hass, EVENT_BUS)

    client, result = await start_fix(hass, hass_client)
    assert result["step_id"] == "change"
    assert result["description_placeholders"] == {
        "title": TITLE,
        "group": "3.1",
        "groups": "4.2, 5.1",
    }
    field = result["data_schema"][0]
    assert field["name"] == CONF_GROUP
    assert field["default"] == OTHER
    assert [o["value"] for o in field["selector"]["select"]["options"]] == [
        OTHER,
        "GPV5.1",
    ]

    result = await submit_fix(client, result["flow_id"], {CONF_GROUP: OTHER})
    assert result["type"] == "create_entry"
    await hass.async_block_till_done()

    assert mock_config_entry.data[CONF_GROUP] == OTHER
    assert mock_config_entry.data[CONF_GROUP_MANUAL] is True
    data = mock_config_entry.runtime_data.data
    assert data.group == OTHER
    assert data.extra_groups == ["GPV5.1"]
    # Today keeps its past; the rest is the new group.
    assert data.days[TODAY] == slots(("10:00", "12:00"))
    assert fake_dtek.schedule_forms[-1]["data[2][value]"] == FORCE_UPDATE_FACT
    changed = bus_events(events, "group_changed")
    assert [(e["previous_group"], e["group"]) for e in changed] == [(GROUP, OTHER)]
    assert issue(hass) is None


async def test_fix_flow_when_the_main_group_is_back(
    hass: HomeAssistant,
    hass_client: ClientSessionGenerator,
    fake_dtek: FakeDtek,
    mock_config_entry: MockConfigEntry,
) -> None:
    """Nothing changes when DTEK lists the main group before the form is sent."""
    await setup_entry(hass, mock_config_entry)
    await answer(hass, fake_dtek, mock_config_entry, [OTHER])
    client, result = await start_fix(hass, hass_client)

    await answer(hass, fake_dtek, mock_config_entry, [GROUP, OTHER], 1)
    result = await submit_fix(client, result["flow_id"], {CONF_GROUP: OTHER})
    assert result["type"] == "abort"
    assert result["reason"] == "group_listed"
    assert mock_config_entry.runtime_data.data.group == GROUP
    assert mock_config_entry.data[CONF_GROUP] == GROUP


async def test_fix_flow_of_an_unloaded_entry(
    hass: HomeAssistant,
    hass_client: ClientSessionGenerator,
    fake_dtek: FakeDtek,
    mock_config_entry: MockConfigEntry,
) -> None:
    """An entry that is not loaded can't change its group."""
    await setup_entry(hass, mock_config_entry)
    await answer(hass, fake_dtek, mock_config_entry, [OTHER])
    await hass.config_entries.async_unload(mock_config_entry.entry_id)
    _, result = await start_fix(hass, hass_client)
    assert result["type"] == "abort"
    assert result["reason"] == "entry_not_loaded"


async def test_issue_back_after_restart(
    hass: HomeAssistant,
    fake_dtek: FakeDtek,
    mock_config_entry: MockConfigEntry,
    hass_storage: dict[str, Any],
) -> None:
    """The answers counted are stored: the issue is back before DTEK answers."""
    await setup_entry(hass, mock_config_entry)
    await answer(hass, fake_dtek, mock_config_entry, [OTHER])

    # A restart forgets the issues that are not persistent.
    ir.async_delete_issue(hass, DOMAIN, ISSUE_ID)
    fake_dtek.ajax_error = aiohttp.ClientConnectionError()
    await hass.config_entries.async_reload(mock_config_entry.entry_id)
    await hass.async_block_till_done()
    assert stored(hass_storage)["main_missing"] == GROUP_REMOVAL_UPDATES
    assert issue(hass).translation_placeholders["groups"] == "4.2"


async def test_issue_gone_with_the_group_or_the_entry(
    hass: HomeAssistant,
    fake_dtek: FakeDtek,
    mock_config_entry: MockConfigEntry,
    entry_data: dict[str, Any],
) -> None:
    """Reconfiguring the group or removing the entry takes the issue away."""
    await setup_entry(hass, mock_config_entry)
    await answer(hass, fake_dtek, mock_config_entry, [OTHER])
    assert issue(hass) is not None

    # Reconfigure to the group DTEK lists: the Store belongs to another group.
    hass.config_entries.async_update_entry(
        mock_config_entry, data={**entry_data, CONF_GROUP: OTHER}
    )
    fake_dtek.ajax_error = aiohttp.ClientConnectionError()
    await hass.config_entries.async_reload(mock_config_entry.entry_id)
    await hass.async_block_till_done()
    assert issue(hass) is None

    # DTEK lists another group alone again, then the entry is removed.
    fake_dtek.ajax_error = None
    await answer(hass, fake_dtek, mock_config_entry, ["GPV5.1"])
    assert issue(hass) is not None
    assert await hass.config_entries.async_remove(mock_config_entry.entry_id)
    await hass.async_block_till_done()
    assert issue(hass) is None
