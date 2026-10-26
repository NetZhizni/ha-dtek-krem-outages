"""Fixtures for DTEK KREM Outages tests."""

from __future__ import annotations

import base64
from datetime import date, datetime, timedelta
import json
from pathlib import Path
from typing import Any
from urllib.parse import quote

from freezegun.api import FrozenDateTimeFactory
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.test_util.aiohttp import (
    AiohttpClientMocker,
    AiohttpClientMockResponse,
)

from custom_components.dtek_krem_outages.const import (
    CONF_GROUP,
    CONF_GROUP_MANUAL,
    CONF_HOUSE,
    CONF_SETTLEMENT,
    CONF_STREET,
    CSRF_COOKIE,
    DEFAULT_OPTIONS,
    DOMAIN,
    MIRROR_URL,
    SITE_AJAX_PATH,
    SITE_BASE_URL,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.util import dt as dt_util

AJAX_URL = f"{SITE_BASE_URL}{SITE_AJAX_PATH}"
ENTRY_ID = "01TESTENTRY"
FIXTURES = Path(__file__).parent / "fixtures"
KYIV = dt_util.get_time_zone("Europe/Kyiv")

SETTLEMENT = "м. Бориспіль"
STREET = "вул. Нечая Івана"
HOUSE = "43"
GROUP = "GPV3.1"
TITLE = f"{SETTLEMENT}, {STREET}, {HOUSE}"

# 2026-10-18 10:10 in Kyiv (UTC+3).
NOW = datetime(2026, 10, 18, 7, 10, tzinfo=dt_util.UTC)
TODAY = date(2026, 10, 18)
TOMORROW = TODAY + timedelta(days=1)

_PAIR_VALUES = {
    "11": "yes",
    "00": "no",
    "01": "first",
    "10": "second",
    "??": "maybe",
    "?1": "mfirst",
    "1?": "msecond",
}


def load_fixture_json(name: str) -> Any:
    """Load a JSON fixture."""
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def slots(*outages: tuple[str, str], possible: tuple[tuple[str, str], ...] = ()) -> str:
    """Build 48 slots with outages (and possible outages) between HH:MM times."""
    chars = ["1"] * 48

    def index(value: str) -> int:
        hours, minutes = value.split(":")
        return int(hours) * 2 + int(minutes) // 30

    for marks, char in ((outages, "0"), (possible, "?")):
        for start, end in marks:
            for i in range(index(start), index(end)):
                chars[i] = char
    return "".join(chars)


def hours_from_slots(value: str) -> dict[str, str]:
    """Convert 48 slots back to the 24 hourly DTEK values."""
    return {
        str(hour + 1): _PAIR_VALUES[value[hour * 2 : hour * 2 + 2]]
        for hour in range(24)
    }


def day_key(day: date) -> str:
    """Return the DTEK key of a day: Unix time of the local midnight."""
    return str(int(datetime(day.year, day.month, day.day, tzinfo=KYIV).timestamp()))


def make_fact(
    days: dict[date, dict[str, str]], update: str = "18.10.2026 09:00"
) -> dict[str, Any]:
    """Return a raw ``fact`` object from slots by day and group."""
    return {
        "data": {
            day_key(day): {group: hours_from_slots(s) for group, s in groups.items()}
            for day, groups in days.items()
        },
        "update": update,
        "today": int(day_key(TODAY)),
    }


def make_preset(weekly: dict[str, dict[int, str]], update: str) -> dict[str, Any]:
    """Return a raw ``preset`` object from slots by group and weekday."""
    return {
        "days": {"1": "Понеділок"},
        "sch_names": {"GPV3.1": "Черга 3.1"},
        "time_type": {"yes": "Світло є"},
        "data": {
            group: {str(day): hours_from_slots(s) for day, s in days.items()}
            for group, days in weekly.items()
        },
        "updateFact": update,
    }


def make_house(
    groups: list[str] | None = None,
    reason: str = "",
    start: str = "",
    end: str = "",
) -> dict[str, Any]:
    """Return a raw ``getHomeNum`` house."""
    return {
        "sub_type": reason,
        "start_date": start,
        "end_date": end,
        "type": "2" if reason else "",
        "sub_type_reason": [GROUP] if groups is None else groups,
        "voluntarily": None,
        "cek": None,
    }


def unmask(masked: str) -> str:
    """Undo Yii2 token masking (what the server does)."""
    raw = base64.urlsafe_b64decode(masked)
    half = len(raw) // 2
    return bytes(a ^ b for a, b in zip(raw[:half], raw[half:], strict=True)).decode()


class FakeDtek:
    """The DTEK ajax endpoint and the mirror, backed by plain attributes."""

    token = "Fz3qUb1L0aW7xN2cR5tY8vK4mH6pJ9sD"  # noqa: S105 (fake CSRF token)

    def __init__(self, aioclient_mock: AiohttpClientMocker) -> None:
        """Initialize with one street, two houses and a schedule for today."""
        self._mock = aioclient_mock
        self.streets: dict[str, list[str]] = {
            SETTLEMENT: [STREET, "вул. Київський Шлях"],
            "с. Буча": ["Без вулиці"],
        }
        self.houses: dict[str, dict[str, Any]] = {
            HOUSE: make_house(),
            "8 а": make_house(["GPV3.1", "GPV4.2"]),
            "10": make_house([]),
            "2": make_house(),
        }
        self.days: dict[date, dict[str, str]] = {
            TODAY: {
                GROUP: slots(("12:00", "14:00"), ("18:00", "20:30")),
                "GPV4.2": slots(("08:00", "12:00")),
            }
        }
        self.update = "18.10.2026 09:00"
        self.weekly: dict[str, dict[int, str]] = {
            GROUP: {day: slots(possible=(("16:00", "20:00"),)) for day in range(1, 8)},
            "GPV4.2": {day: slots() for day in range(1, 8)},
        }
        self.mirror_days: dict[date, dict[str, str]] | None = None
        self.mirror_update = "18.10.2026 09:00"
        self.ajax_error: Exception | None = None
        self.ajax_status = 200
        self.ajax_text: str | None = None
        self.mirror_error: Exception | None = None
        self.mirror_status = 200
        self.issued_tokens = 0
        self.forms: list[dict[str, str]] = []
        self.mirror_requests = 0

    @property
    def cookie_value(self) -> str:
        """Return the CSRF cookie the way Yii2 sends it."""
        serialized = (
            f'a:2:{{i:0;s:{len(CSRF_COOKIE)}:"{CSRF_COOKIE}";'
            f'i:1;s:{len(self.token)}:"{self.token}";}}'
        )
        return quote("0" * 64 + serialized)

    async def ajax(self, method: str, url: Any, data: Any) -> AiohttpClientMockResponse:
        """Answer a POST to /ua/ajax."""
        if self.ajax_error is not None:
            raise self.ajax_error
        if self.ajax_text is not None:
            return AiohttpClientMockResponse(
                method, url, status=self.ajax_status, text=self.ajax_text
            )
        headers = self._mock.mock_calls[-1][3] or {}
        masked = headers.get("X-CSRF-Token")
        if masked is None or unmask(masked) != self.token:
            self.issued_tokens += 1
            return AiohttpClientMockResponse(
                method,
                url,
                status=400,
                text="Bad Request (#400): Не вдалося перевірити передані дані.",
                cookies={CSRF_COOKIE: self.cookie_value},
            )
        form = dict(data)
        self.forms.append(form)
        if self.ajax_status != 200:
            return AiohttpClientMockResponse(method, url, status=self.ajax_status)
        if form["method"] == "getStreets":
            return self._json(method, url, {"result": True, "streets": self.streets})
        city = form.get("data[0][value]")
        street = form.get("data[1][value]")
        if city not in self.streets or street not in self.streets[city]:
            return self._json(method, url, {"result": False, "text": "Error"})
        answer: dict[str, Any] = {
            "result": True,
            "data": self.houses,
            "showCurOutageParam": True,
            "updateTimestamp": "10:10 18.10.2026",
        }
        update_fact = form.get("data[2][value]", "")
        # PHP truthiness: "" and "0" are false.
        if update_fact not in ("", "0") and update_fact != self.update:
            answer["fact"] = make_fact(self.days, self.update)
            answer["preset"] = make_preset(self.weekly, self.update)
        return self._json(method, url, answer)

    async def mirror(
        self, method: str, url: Any, data: Any
    ) -> AiohttpClientMockResponse:
        """Answer a GET of the mirror file."""
        self.mirror_requests += 1
        if self.mirror_error is not None:
            raise self.mirror_error
        if self.mirror_status != 200:
            return AiohttpClientMockResponse(method, url, status=self.mirror_status)
        days = self.days if self.mirror_days is None else self.mirror_days
        return self._json(
            method,
            url,
            {
                "regionId": "kyiv-region",
                "lastUpdated": "2026-10-18T07:00:00.000Z",
                "fact": make_fact(days, self.mirror_update),
                "preset": make_preset(self.weekly, self.mirror_update),
            },
        )

    @staticmethod
    def _json(method: str, url: Any, payload: Any) -> AiohttpClientMockResponse:
        return AiohttpClientMockResponse(
            method,
            url,
            text=json.dumps(payload, ensure_ascii=False),
            headers={"Content-Type": "text/html; charset=UTF-8"},
        )

    @property
    def schedule_forms(self) -> list[dict[str, str]]:
        """Return the getHomeNum requests that passed the CSRF check."""
        return [f for f in self.forms if f["method"] == "getHomeNum"]


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations: None) -> None:
    """Enable custom integrations in all tests."""


@pytest.fixture(autouse=True)
def frozen_now(freezer: FrozenDateTimeFactory) -> FrozenDateTimeFactory:
    """Start every test at 2026-10-18 10:10 Kyiv time."""
    freezer.move_to(NOW)
    return freezer


@pytest.fixture
def fake_dtek(aioclient_mock: AiohttpClientMocker) -> FakeDtek:
    """Route DTEK and mirror requests to a fake server."""
    fake = FakeDtek(aioclient_mock)
    aioclient_mock.post(AJAX_URL, side_effect=fake.ajax)
    aioclient_mock.get(MIRROR_URL, side_effect=fake.mirror)
    return fake


@pytest.fixture
def options() -> dict[str, Any]:
    """Return the entry options; override to change them."""
    return dict(DEFAULT_OPTIONS)


@pytest.fixture
def entry_data() -> dict[str, Any]:
    """Return the entry data; override to change it."""
    return {
        CONF_SETTLEMENT: SETTLEMENT,
        CONF_STREET: STREET,
        CONF_HOUSE: HOUSE,
        CONF_GROUP: GROUP,
        CONF_GROUP_MANUAL: False,
    }


@pytest.fixture
def mock_config_entry(
    options: dict[str, Any], entry_data: dict[str, Any]
) -> MockConfigEntry:
    """Return a config entry for the test address."""
    return MockConfigEntry(
        domain=DOMAIN,
        title=TITLE,
        unique_id=f"{SETTLEMENT}|{STREET}|{HOUSE}",
        entry_id=ENTRY_ID,
        data=entry_data,
        options=options,
    )


async def setup_entry(hass: HomeAssistant, entry: MockConfigEntry) -> None:
    """Add (unless already added) and set up a config entry."""
    if hass.config_entries.async_get_entry(entry.entry_id) is None:
        entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()


def get_entity_id(hass: HomeAssistant, platform: str, key: str) -> str:
    """Return the entity ID of an entity of the test entry."""
    entity_id = er.async_get(hass).async_get_entity_id(
        platform, DOMAIN, f"{ENTRY_ID}_{key}"
    )
    assert entity_id is not None
    return entity_id


def kyiv(day: date, time: str) -> datetime:
    """Return a Kyiv datetime for a day and ``HH:MM``."""
    hours, minutes = (int(part) for part in time.split(":"))
    return datetime(day.year, day.month, day.day, hours, minutes, tzinfo=KYIV)
