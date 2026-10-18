"""Async client for the outage data of DTEK KREM (https://www.dtek-krem.com.ua).

Facts verified against the live site on 2026-10-18 (samples in tests/fixtures):

* ``/ua/shutdowns`` and every other page are behind Imperva Incapsula: a GET
  returns a JavaScript challenge that only a browser can pass. POST requests
  to ``/ua/ajax`` are not challenged. The shutdowns page itself loads its data
  from this endpoint, and so does this client.
* ``/ua/ajax`` is a Yii2 action with CSRF validation. A POST without a token
  answers HTTP 400 and sets the ``_csrf-dtek-krem`` cookie. Yii2 signs that
  cookie but does not encrypt it: it holds the PHP-serialized token. A request
  is accepted when the ``X-CSRF-Token`` header carries the masked token,
  ``base64url(mask + (mask XOR token))`` with a random mask, which is what the
  page embeds in ``<meta name="csrf-token">``.
* ``method=getStreets`` answers ``{"result": true, "streets": {settlement:
  [street, ...]}}``: about 1200 settlements, 470 KB.
* ``method=getHomeNum`` takes ``data[i][name]``/``data[i][value]`` pairs for
  ``city``, ``street`` and ``updateFact`` and answers ``{"result": true,
  "data": {house: {...}}, ...}``. A house has ``sub_type`` (reason of the
  current outage, ``""`` when there is none), ``start_date``/``end_date``
  (``"HH:MM dd.mm.YYYY"`` or ``""``), ``type`` (``"2"`` or ``""``),
  ``sub_type_reason`` (groups: usually one, sometimes none or several) and
  ``voluntarily``/``cek`` (always null so far). ``fact`` and ``preset`` are
  added only when ``updateFact`` is truthy in PHP (``""`` and ``"0"`` are
  not) and differs from the current ``fact.update`` (``"dd.mm.YYYY HH:MM"``),
  so that value works as a version.
  Unknown settlements or streets give ``{"result": false, "text": "Error"}``.
* ``fact`` is ``{"data": {day: {group: {hour: value}}}, "update": ...,
  "today": day}`` with ``day`` the Unix time of local midnight; ``data`` is
  ``[]`` when nothing is published. ``preset`` is ``{"data": {group:
  {weekday: {hour: value}}}, "updateFact": ..., ...}`` with ISO weekdays.
  Hour values are described in ``schedule.py``.
* The mirror (``MIRROR_URL``) republishes ``fact`` and ``preset`` unchanged
  next to ``lastUpdated`` (ISO, UTC). It has no address data.
"""

from __future__ import annotations

import asyncio
import base64
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from datetime import date, datetime, tzinfo
import logging
import re
import secrets
from typing import Any
from urllib.parse import unquote

import aiohttp

from homeassistant.const import __version__ as ha_version
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_create_clientsession
from homeassistant.loader import async_get_integration
from homeassistant.util import dt as dt_util
from homeassistant.util.hass_dict import HassKey
from homeassistant.util.json import json_loads

from .const import (
    API_TIMEOUT,
    CSRF_COOKIE,
    DOMAIN,
    GROUPS,
    MIRROR_URL,
    OUTAGE_KIND_EMERGENCY,
    OUTAGE_KIND_OTHER,
    OUTAGE_KIND_PLANNED,
    OUTAGE_KIND_STABILIZATION,
    PROJECT_URL,
    SITE_AJAX_PATH,
    SITE_BASE_URL,
    SITE_REFERER_PATH,
    TIMEZONE,
)
from .schedule import is_valid_slots, parse_hours

_LOGGER = logging.getLogger(__name__)

DATA_CLIENT: HassKey[DtekClient] = HassKey(f"{DOMAIN}_client")

UPDATE_FORMAT = "%d.%m.%Y %H:%M"
HOUSE_DATE_FORMAT = "%H:%M %d.%m.%Y"

_CSRF_TOKEN_RE = re.compile(r'i:1;s:\d+:"([^"]+)"')
_CHALLENGE_MARKER = "_Incapsula_Resource"


class DtekError(Exception):
    """Base error raised by the client."""


class DtekConnectionError(DtekError):
    """The server could not be reached."""


class DtekBlockedError(DtekConnectionError):
    """The request got the anti-bot challenge instead of data."""


class DtekResponseError(DtekError):
    """The server answered with an unexpected status or payload."""


class DtekNotFoundError(DtekError):
    """The settlement or street is unknown to DTEK."""


def build_user_agent(version: str | None = None) -> str:
    """Return the User-Agent sent to DTEK, with the integration version."""
    product = f"ha-dtek-krem-outages/{version}" if version else "ha-dtek-krem-outages"
    return f"HomeAssistant/{ha_version} {product} (+{PROJECT_URL})"


def extract_csrf_token(cookie_value: str) -> str | None:
    """Return the raw token from a Yii2 CSRF cookie value."""
    match = _CSRF_TOKEN_RE.search(unquote(cookie_value))
    return match.group(1) if match else None


def mask_csrf_token(token: str, mask: bytes | None = None) -> str:
    """Mask a token the way Yii2 ``Security::maskToken`` does."""
    raw = token.encode()
    if mask is None:
        mask = secrets.token_bytes(len(raw))
    masked = bytes(a ^ b for a, b in zip(mask, raw, strict=True))
    return base64.urlsafe_b64encode(mask + masked).decode()


def parse_local_datetime(value: Any, fmt: str, tz: tzinfo) -> datetime | None:
    """Parse a DTEK local time string; empty or invalid values give None."""
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.strptime(value.strip(), fmt)  # noqa: DTZ007
    except ValueError:
        return None
    return parsed.replace(tzinfo=tz)


def parse_day(value: Any, tz: tzinfo) -> date | None:
    """Parse a day key (Unix time of local midnight) into a local date."""
    if isinstance(value, bool):
        return None
    try:
        timestamp = int(value)
    except (TypeError, ValueError):
        return None
    try:
        return datetime.fromtimestamp(timestamp, tz).date()
    except (OverflowError, OSError, ValueError):
        return None


def classify_reason(reason: str) -> str:
    """Return the kind of an outage from its DTEK description."""
    text = reason.casefold()
    if "стабіліз" in text:
        return OUTAGE_KIND_STABILIZATION
    if "аварій" in text or "екстрен" in text:
        return OUTAGE_KIND_EMERGENCY
    if "план" in text:
        return OUTAGE_KIND_PLANNED
    return OUTAGE_KIND_OTHER


def _as_str(value: Any) -> str:
    return value.strip() if isinstance(value, str) else ""


def _isoformat(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None


@dataclass(frozen=True, slots=True, kw_only=True)
class AddressOutage:
    """An outage DTEK reports for one address right now."""

    reason: str
    kind: str
    start: datetime | None = None
    end: datetime | None = None
    type: str = ""

    def is_active(self, now: datetime) -> bool:
        """Return True while ``now`` is between start and end."""
        if self.start is not None and now < self.start:
            return False
        return self.end is None or now < self.end

    def as_dict(self) -> dict[str, Any]:
        """Return a JSON serializable form."""
        return {
            "reason": self.reason,
            "kind": self.kind,
            "start": _isoformat(self.start),
            "end": _isoformat(self.end),
            "type": self.type,
        }

    @classmethod
    def from_dict(cls, data: Any) -> AddressOutage | None:
        """Restore an outage saved with ``as_dict``."""
        if not isinstance(data, Mapping) or not _as_str(data.get("reason")):
            return None
        reason = _as_str(data.get("reason"))
        return cls(
            reason=reason,
            kind=_as_str(data.get("kind")) or classify_reason(reason),
            start=_parse_iso(data.get("start")),
            end=_parse_iso(data.get("end")),
            type=_as_str(data.get("type")),
        )


def _parse_iso(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        return dt_util.parse_datetime(value)
    except ValueError:
        return None


@dataclass(frozen=True, slots=True, kw_only=True)
class House:
    """A house of a street with its groups and current outage."""

    number: str
    groups: list[str] = field(default_factory=list)
    outage: AddressOutage | None = None

    @classmethod
    def from_api(cls, number: str, raw: Mapping[str, Any], tz: tzinfo) -> House:
        """Build a house from a ``getHomeNum`` item."""
        reasons = raw.get("sub_type_reason")
        groups = [
            group
            for group in (reasons if isinstance(reasons, list) else [])
            if group in GROUPS
        ]
        outage = None
        if reason := _as_str(raw.get("sub_type")):
            outage = AddressOutage(
                reason=reason,
                kind=classify_reason(reason),
                start=parse_local_datetime(
                    raw.get("start_date"), HOUSE_DATE_FORMAT, tz
                ),
                end=parse_local_datetime(raw.get("end_date"), HOUSE_DATE_FORMAT, tz),
                type=_as_str(raw.get("type")),
            )
        return cls(number=number, groups=groups, outage=outage)


@dataclass(frozen=True, slots=True, kw_only=True)
class Fact:
    """The actual schedule of all groups for today and, once known, tomorrow."""

    days: dict[date, dict[str, str]] = field(default_factory=dict)
    update: str | None = None
    updated_at: datetime | None = None
    today: date | None = None

    def for_group(self, group: str) -> dict[date, str]:
        """Return the slots of one group by day."""
        return {
            day: groups[group] for day, groups in self.days.items() if group in groups
        }

    @classmethod
    def from_api(cls, raw: Any, tz: tzinfo) -> Fact | None:
        """Parse a ``fact`` object; None if it is not an object."""
        if not isinstance(raw, Mapping):
            return None
        days: dict[date, dict[str, str]] = {}
        data = raw.get("data")
        if isinstance(data, Mapping):
            for key, groups in data.items():
                day = parse_day(key, tz)
                if day is None or not isinstance(groups, Mapping):
                    continue
                parsed = {
                    group: slots
                    for group, hours in groups.items()
                    if group in GROUPS and (slots := parse_hours(hours))
                }
                if parsed:
                    days[day] = parsed
        update = _as_str(raw.get("update")) or None
        return cls(
            days=days,
            update=update,
            updated_at=parse_local_datetime(update, UPDATE_FORMAT, tz),
            today=parse_day(raw.get("today"), tz),
        )


@dataclass(frozen=True, slots=True, kw_only=True)
class Preset:
    """The weekly schedule of possible outages of all groups."""

    groups: dict[str, dict[int, str]] = field(default_factory=dict)
    update: str | None = None

    def for_group(self, group: str) -> dict[int, str]:
        """Return the slots of one group by ISO weekday."""
        return dict(self.groups.get(group, {}))

    @classmethod
    def from_api(cls, raw: Any) -> Preset | None:
        """Parse a ``preset`` object; None if it is not an object."""
        if not isinstance(raw, Mapping):
            return None
        groups: dict[str, dict[int, str]] = {}
        data = raw.get("data")
        if isinstance(data, Mapping):
            for group, weekdays in data.items():
                if group not in GROUPS or not isinstance(weekdays, Mapping):
                    continue
                parsed: dict[int, str] = {}
                for weekday, hours in weekdays.items():
                    try:
                        number = int(weekday)
                    except (TypeError, ValueError):
                        continue
                    if 1 <= number <= 7 and (slots := parse_hours(hours)):
                        parsed[number] = slots
                if parsed:
                    groups[group] = parsed
        return cls(groups=groups, update=_as_str(raw.get("updateFact")) or None)


def preset_from_dict(data: Any) -> dict[int, str]:
    """Restore weekly slots saved as ``{"1": slots, ...}``."""
    if not isinstance(data, Mapping):
        return {}
    result: dict[int, str] = {}
    for weekday, slots in data.items():
        try:
            number = int(weekday)
        except (TypeError, ValueError):
            continue
        if 1 <= number <= 7 and is_valid_slots(slots):
            result[number] = slots
    return result


@dataclass(frozen=True, slots=True, kw_only=True)
class StreetData:
    """The ``getHomeNum`` answer for one street."""

    houses: dict[str, House] = field(default_factory=dict)
    fact: Fact | None = None
    preset: Preset | None = None


@dataclass(frozen=True, slots=True, kw_only=True)
class MirrorData:
    """The mirror copy of ``fact`` and ``preset``."""

    fact: Fact | None = None
    preset: Preset | None = None
    updated_at: datetime | None = None


def _form_pairs(pairs: Iterable[tuple[str, str]]) -> dict[str, str]:
    """Encode name/value pairs like jQuery's ``serializeArray``."""
    form: dict[str, str] = {}
    for index, (name, value) in enumerate(pairs):
        form[f"data[{index}][name]"] = name
        form[f"data[{index}][value]"] = value
    return form


class DtekClient:
    """Minimal async client for the DTEK KREM ajax endpoint and the mirror."""

    def __init__(
        self,
        session: aiohttp.ClientSession,
        tz: tzinfo,
        *,
        base_url: str = SITE_BASE_URL,
        mirror_url: str = MIRROR_URL,
        user_agent: str | None = None,
    ) -> None:
        """Initialize the client."""
        self._session = session
        self.tz = tz
        self._base_url = base_url.rstrip("/")
        self._mirror_url = mirror_url
        self._user_agent = user_agent or build_user_agent()
        self._csrf_token: str | None = None
        self._bootstrap_lock = asyncio.Lock()

    async def async_get_streets(self) -> dict[str, list[str]]:
        """Return every settlement with its streets."""
        payload = await self._async_ajax({"method": "getStreets"})
        streets = payload.get("streets")
        if not isinstance(streets, Mapping):
            raise DtekResponseError("Expected a streets object")
        result: dict[str, list[str]] = {}
        for settlement, names in streets.items():
            if not isinstance(settlement, str) or not isinstance(names, list):
                continue
            result[settlement] = [name for name in names if isinstance(name, str)]
        if not result:
            raise DtekResponseError("Empty streets list")
        return result

    async def async_get_street(
        self, settlement: str, street: str, update_fact: str | None = None
    ) -> StreetData:
        """Return the houses of a street; ``fact`` and ``preset`` if newer.

        ``update_fact`` is the last known ``fact.update``; an empty value
        means "don't send the schedule". ``FORCE_UPDATE_FACT`` forces it.
        """
        payload = await self._async_ajax(
            {
                "method": "getHomeNum",
                **_form_pairs(
                    (
                        ("city", settlement),
                        ("street", street),
                        ("updateFact", update_fact or ""),
                    )
                ),
            }
        )
        houses: dict[str, House] = {}
        data = payload.get("data")
        if isinstance(data, Mapping):
            for number, raw in data.items():
                if isinstance(number, str) and isinstance(raw, Mapping):
                    houses[number] = House.from_api(number, raw, self.tz)
        return StreetData(
            houses=houses,
            fact=Fact.from_api(payload.get("fact"), self.tz),
            preset=Preset.from_api(payload.get("preset")),
        )

    async def async_get_mirror(self) -> MirrorData:
        """Return ``fact`` and ``preset`` from the mirror."""
        try:
            async with self._session.get(
                self._mirror_url,
                headers={"User-Agent": self._user_agent},
                timeout=aiohttp.ClientTimeout(total=API_TIMEOUT),
            ) as response:
                if response.status != 200:
                    raise DtekResponseError(
                        f"Unexpected HTTP status {response.status} from the mirror"
                    )
                text = await response.text()
        except TimeoutError as err:
            raise DtekConnectionError("Timeout while requesting the mirror") from err
        except aiohttp.ClientError as err:
            raise DtekConnectionError(f"Error requesting the mirror: {err}") from err
        try:
            payload = json_loads(text)
        except ValueError as err:
            raise DtekResponseError("Invalid JSON from the mirror") from err
        if not isinstance(payload, Mapping):
            raise DtekResponseError("Expected an object from the mirror")
        return MirrorData(
            fact=Fact.from_api(payload.get("fact"), self.tz),
            preset=Preset.from_api(payload.get("preset")),
            updated_at=_parse_iso(payload.get("lastUpdated")),
        )

    async def _async_ajax(self, form: Mapping[str, str]) -> Mapping[str, Any]:
        """POST to the ajax endpoint with a CSRF token; retry once on HTTP 400."""
        token = await self._async_token()
        status, payload = await self._async_post(form, token)
        if status == 400:
            # A rejected token usually comes back with a fresh cookie; if not,
            # drop the cookie and ask for a new one.
            token = await self._async_token(stale=token)
            status, payload = await self._async_post(form, token)
        if status != 200:
            raise DtekResponseError(f"Unexpected HTTP status {status} from DTEK")
        if not isinstance(payload, Mapping):
            raise DtekResponseError("Expected an object from DTEK")
        if payload.get("result") is not True:
            raise DtekNotFoundError(str(payload.get("text") or "Unknown address"))
        return payload

    async def _async_token(self, stale: str | None = None) -> str:
        """Return the CSRF token, asking the server for one if needed.

        ``stale`` is a token the server just rejected.
        """
        async with self._bootstrap_lock:
            if stale is not None and self._csrf_token == stale:
                self._csrf_token = None
                self._session.cookie_jar.clear(lambda cookie: cookie.key == CSRF_COOKIE)
            if self._csrf_token is None:
                # Without a token the server answers 400 and sets the cookie.
                await self._async_post({"method": "getHomeNum"}, None)
            if self._csrf_token is None:
                raise DtekResponseError("DTEK did not issue a CSRF cookie")
            return self._csrf_token

    async def _async_post(
        self, form: Mapping[str, str], token: str | None
    ) -> tuple[int, Any]:
        """POST a form; return the status and the parsed JSON (None if not 200)."""
        headers = {
            "User-Agent": self._user_agent,
            "Accept": "application/json, text/javascript, */*; q=0.01",
            "X-Requested-With": "XMLHttpRequest",
            "Origin": self._base_url,
            "Referer": f"{self._base_url}{SITE_REFERER_PATH}",
        }
        if token is not None:
            headers["X-CSRF-Token"] = mask_csrf_token(token)
        try:
            async with self._session.post(
                f"{self._base_url}{SITE_AJAX_PATH}",
                data=dict(form),
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=API_TIMEOUT),
            ) as response:
                if (cookie := response.cookies.get(CSRF_COOKIE)) is not None and (
                    new_token := extract_csrf_token(cookie.value)
                ):
                    self._csrf_token = new_token
                status = response.status
                text = await response.text()
        except TimeoutError as err:
            raise DtekConnectionError("Timeout while requesting DTEK") from err
        except aiohttp.ClientError as err:
            raise DtekConnectionError(f"Error requesting DTEK: {err}") from err
        if _CHALLENGE_MARKER in text:
            raise DtekBlockedError("DTEK answered with the anti-bot challenge")
        if status != 200:
            return status, None
        try:
            return status, json_loads(text)
        except ValueError as err:
            raise DtekResponseError("Invalid JSON from DTEK") from err


async def async_get_client(hass: HomeAssistant) -> DtekClient:
    """Return the client shared by all entries and config flows.

    It has its own session so the DTEK cookies stay out of the shared one.
    The version in the User-Agent comes from manifest.json, its only source.
    """
    if (client := hass.data.get(DATA_CLIENT)) is not None:
        return client
    integration = await async_get_integration(hass, DOMAIN)
    tz = await dt_util.async_get_time_zone(TIMEZONE)
    if tz is None:
        raise DtekError(f"Time zone {TIMEZONE} is not available")
    if (client := hass.data.get(DATA_CLIENT)) is not None:
        return client
    version = str(integration.version) if integration.version else None
    client = hass.data[DATA_CLIENT] = DtekClient(
        async_create_clientsession(hass, cookie_jar=aiohttp.CookieJar()),
        tz,
        user_agent=build_user_agent(version),
    )
    return client
