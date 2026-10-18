"""Tests for the DTEK client and parsers."""

from __future__ import annotations

from datetime import date

import aiohttp
import pytest
from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMocker

from custom_components.dtek_krem_outages.api import (
    AddressOutage,
    DtekBlockedError,
    DtekClient,
    DtekConnectionError,
    DtekNotFoundError,
    DtekResponseError,
    Fact,
    House,
    Preset,
    async_get_client,
    build_user_agent,
    classify_reason,
    extract_csrf_token,
    mask_csrf_token,
    parse_day,
)
from custom_components.dtek_krem_outages.const import (
    FORCE_UPDATE_FACT,
    OUTAGE_KIND_EMERGENCY,
    OUTAGE_KIND_OTHER,
    OUTAGE_KIND_PLANNED,
    OUTAGE_KIND_STABILIZATION,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .conftest import (
    AJAX_URL,
    HOUSE,
    KYIV,
    SETTLEMENT,
    STREET,
    TODAY,
    FakeDtek,
    kyiv,
    load_fixture_json,
    slots,
    unmask,
)


@pytest.fixture
async def client(hass: HomeAssistant, fake_dtek: FakeDtek) -> DtekClient:
    """Return a client using the mocked session."""
    return await async_get_client(hass)


def test_csrf_token_helpers() -> None:
    """The token is read from the Yii cookie and masked like Yii does."""
    fake = FakeDtek.__new__(FakeDtek)
    assert extract_csrf_token(fake.cookie_value) == FakeDtek.token
    assert extract_csrf_token("garbage") is None
    masked = mask_csrf_token(FakeDtek.token)
    assert unmask(masked) == FakeDtek.token
    # A random mask each time.
    assert masked != mask_csrf_token(FakeDtek.token)
    # mask + (mask XOR token), base64url with padding as in Yii2.
    assert mask_csrf_token("ab", b"\x01\x02") == "AQJgYA=="


def test_user_agent() -> None:
    """The User-Agent names the integration and its version."""
    assert "ha-dtek-krem-outages/0.1.0" in build_user_agent("0.1.0")
    assert "ha-dtek-krem-outages (" in build_user_agent()


def test_parse_real_answer() -> None:
    """A real getHomeNum answer (2026-10-18) parses completely."""
    raw = load_fixture_json("home_num.json")
    fact = Fact.from_api(raw["fact"], KYIV)
    assert fact is not None
    assert fact.update == "18.10.2026 19:27"
    assert fact.updated_at == kyiv(TODAY, "19:27")
    assert fact.today == TODAY
    assert list(fact.days) == [TODAY]
    assert len(fact.days[TODAY]) == 12
    group = fact.for_group("GPV1.1")[TODAY]
    assert group[24:26] == "00"  # 12:00-13:00 "no"
    assert group[38:40] == "01"  # 19:00-20:00 "first"

    preset = Preset.from_api(raw["preset"])
    assert preset is not None
    assert preset.update == "18.10.2026 19:27"
    assert sorted(preset.for_group("GPV3.1")) == [1, 2, 3, 4, 5, 6, 7]
    assert set("".join(preset.for_group("GPV3.1").values())) <= {"1", "?"}

    house = House.from_api("43", raw["data"]["43"], KYIV)
    assert house.groups == ["GPV3.1"]
    assert house.outage == AddressOutage(
        reason=raw["data"]["43"]["sub_type"],
        kind=OUTAGE_KIND_EMERGENCY,
        start=kyiv(TODAY, "15:24"),
        end=kyiv(TODAY, "23:15"),
        type="2",
    )
    assert House.from_api("21", raw["data"]["21"], KYIV).outage.kind == (
        OUTAGE_KIND_STABILIZATION
    )


def test_parse_real_mirror() -> None:
    """The mirror carries the same objects."""
    raw = load_fixture_json("mirror.json")
    fact = Fact.from_api(raw["fact"], KYIV)
    assert fact.update == "18.10.2026 19:27"
    assert Preset.from_api(raw["preset"]).groups


def test_parse_edge_cases() -> None:
    """Empty and malformed parts are skipped."""
    fact = Fact.from_api({"data": [], "update": "", "today": "x"}, KYIV)
    assert fact == Fact()
    assert Fact.from_api(None, KYIV) is None
    assert Fact.from_api(
        {"data": {"bad": {}, "1792270800": {"GPV9.9": {"1": "no"}}}}, KYIV
    ) == Fact(days={})
    assert Preset.from_api({"data": {"GPV1.1": {"8": {}, "x": {}}}}) == Preset()
    assert parse_day(True, KYIV) is None
    assert parse_day("1792270800", KYIV) == date(2026, 10, 18)

    house = House.from_api(
        "1", {"sub_type": "", "sub_type_reason": ["GPV1.1", "bogus"]}, KYIV
    )
    assert house == House(number="1", groups=["GPV1.1"])
    house = House.from_api("1", {"sub_type": "Щось", "start_date": "bad"}, KYIV)
    assert house.outage.start is None
    assert house.outage.kind == OUTAGE_KIND_OTHER


@pytest.mark.parametrize(
    ("reason", "kind"),
    [
        ("Стабілізаційне відключення (Згідно графіку)", OUTAGE_KIND_STABILIZATION),
        ("Аварійні ремонтні роботи", OUTAGE_KIND_EMERGENCY),
        ("Екстренні відключення (Аварійне без графіку)", OUTAGE_KIND_EMERGENCY),
        ("Планові ремонтні роботи", OUTAGE_KIND_PLANNED),
        ("Інше", OUTAGE_KIND_OTHER),
    ],
)
def test_classify_reason(reason: str, kind: str) -> None:
    """Reasons are grouped into kinds."""
    assert classify_reason(reason) == kind


def test_address_outage_round_trip() -> None:
    """Stored outages restore; activity follows start and end."""
    outage = AddressOutage(
        reason="Аварійні ремонтні роботи",
        kind=OUTAGE_KIND_EMERGENCY,
        start=kyiv(TODAY, "10:00"),
        end=kyiv(TODAY, "12:00"),
        type="2",
    )
    assert AddressOutage.from_dict(outage.as_dict()) == outage
    assert AddressOutage.from_dict({"reason": ""}) is None
    assert not outage.is_active(kyiv(TODAY, "09:59"))
    assert outage.is_active(kyiv(TODAY, "10:00"))
    assert not outage.is_active(kyiv(TODAY, "12:00"))


async def test_get_streets_bootstraps_csrf(
    client: DtekClient, fake_dtek: FakeDtek, aioclient_mock: AiohttpClientMocker
) -> None:
    """The first request gets the cookie, the token is reused afterwards."""
    streets = await client.async_get_streets()
    assert streets[SETTLEMENT] == [STREET, "вул. Київський Шлях"]
    assert fake_dtek.issued_tokens == 1
    # Bootstrap without a token, then the real request with one.
    assert aioclient_mock.call_count == 2
    first_headers = aioclient_mock.mock_calls[0][3]
    assert "X-CSRF-Token" not in first_headers
    headers = aioclient_mock.mock_calls[1][3]
    assert headers["X-Requested-With"] == "XMLHttpRequest"
    assert headers["User-Agent"].startswith("HomeAssistant/")

    await client.async_get_streets()
    assert fake_dtek.issued_tokens == 1
    assert aioclient_mock.call_count == 3


async def test_expired_token_is_renewed(
    client: DtekClient, fake_dtek: FakeDtek
) -> None:
    """HTTP 400 for a known token gets a new one and retries once."""
    await client.async_get_streets()
    fake_dtek.token = "Zz9yXx8wWv7uUt6sSr5qQp4oOn3mMl2k"  # noqa: S105
    await client.async_get_streets()
    assert fake_dtek.issued_tokens == 2


async def test_get_street(client: DtekClient, fake_dtek: FakeDtek) -> None:
    """Houses always come back, the schedule only for another version."""
    data = await client.async_get_street(SETTLEMENT, STREET, FORCE_UPDATE_FACT)
    assert set(data.houses) == {HOUSE, "8 а", "10", "2"}
    assert data.houses["8 а"].groups == ["GPV3.1", "GPV4.2"]
    assert data.fact is not None
    assert data.fact.for_group("GPV3.1")[TODAY] == slots(
        ("12:00", "14:00"), ("18:00", "20:30")
    )
    assert data.preset is not None
    form = fake_dtek.schedule_forms[-1]
    assert form == {
        "method": "getHomeNum",
        "data[0][name]": "city",
        "data[0][value]": SETTLEMENT,
        "data[1][name]": "street",
        "data[1][value]": STREET,
        "data[2][name]": "updateFact",
        "data[2][value]": FORCE_UPDATE_FACT,
    }

    data = await client.async_get_street(SETTLEMENT, STREET, fake_dtek.update)
    assert data.fact is None
    assert data.preset is None
    data = await client.async_get_street(SETTLEMENT, STREET)
    assert data.fact is None
    data = await client.async_get_street(SETTLEMENT, STREET, "0")
    assert data.fact is None


async def test_unknown_street(client: DtekClient) -> None:
    """``result: false`` means an unknown address."""
    with pytest.raises(DtekNotFoundError):
        await client.async_get_street(SETTLEMENT, "вул. Неіснуюча")


@pytest.mark.parametrize(
    ("setup", "error"),
    [
        ({"ajax_error": aiohttp.ClientConnectionError()}, DtekConnectionError),
        ({"ajax_error": TimeoutError()}, DtekConnectionError),
        ({"ajax_status": 503}, DtekResponseError),
        ({"ajax_text": "not json"}, DtekResponseError),
        ({"ajax_text": "[1, 2]"}, DtekResponseError),
        (
            {
                "ajax_text": '<script src="/_Incapsula_Resource?SWJIYLWA=1"></script>',
            },
            DtekBlockedError,
        ),
    ],
)
async def test_ajax_errors(
    client: DtekClient,
    fake_dtek: FakeDtek,
    setup: dict[str, object],
    error: type[Exception],
) -> None:
    """Failures raise the matching error."""
    for key, value in setup.items():
        setattr(fake_dtek, key, value)
    with pytest.raises(error):
        await client.async_get_street(SETTLEMENT, STREET, FORCE_UPDATE_FACT)


async def test_no_csrf_cookie(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """A 400 without the cookie is an error, not a loop."""
    aioclient_mock.post(AJAX_URL, status=400, text="Bad Request")
    client = DtekClient(async_get_clientsession(hass), KYIV)
    with pytest.raises(DtekResponseError, match="CSRF"):
        await client.async_get_streets()


async def test_closed_session_is_replaced(
    hass: HomeAssistant, client: DtekClient, fake_dtek: FakeDtek
) -> None:
    """A session closed by Home Assistant is replaced, not reused."""
    assert await client.async_get_streets()
    await client._session.close()
    assert await client.async_get_streets()
    assert not client._session.closed


async def test_mirror(client: DtekClient, fake_dtek: FakeDtek) -> None:
    """The mirror gives fact and preset."""
    data = await client.async_get_mirror()
    assert data.fact.update == "18.10.2026 09:00"
    assert data.preset.for_group("GPV3.1")
    assert data.updated_at is not None

    fake_dtek.mirror_status = 404
    with pytest.raises(DtekResponseError):
        await client.async_get_mirror()
    fake_dtek.mirror_status = 200
    fake_dtek.mirror_error = aiohttp.ClientConnectionError()
    with pytest.raises(DtekConnectionError):
        await client.async_get_mirror()


async def test_shared_client(hass: HomeAssistant, fake_dtek: FakeDtek) -> None:
    """All entries share one client."""
    assert await async_get_client(hass) is await async_get_client(hass)
