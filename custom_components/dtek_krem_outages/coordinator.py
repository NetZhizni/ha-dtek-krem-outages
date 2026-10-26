"""Data update coordinator for DTEK KREM Outages.

Each update asks DTEK for the street of the entry. The answer always holds
the houses (group and current outage of the address) and holds the schedule
only when it changed since the version we send. If DTEK fails, the schedule
comes from the mirror when it is newer than ours.

The schedule is merged into the stored one instead of replacing it: what
already happened is kept as it was, the future follows the newest data. The
result is saved in a Store, so a restart or an outage of both sources keeps
the last known schedule working.

The ``show*`` flags of the answer are followed like the DTEK page follows
them: a hidden daily schedule clears the days from now on, a hidden weekly
schedule is left out of the calendar. An entry set up by group only has no
address to ask DTEK about and takes the schedule from the mirror.

DTEK can list several groups for one house. The main group is the one of the
entry; the others are followed too, each with its own merged schedule. They
come and go with the DTEK answer: a new group is taken at once, a group that
is no longer listed is dropped after a few answers without it. The schedule
the entities show follows ``groups_mode``: the main group alone, the worst of
all groups slot by slot, or an outage where all groups are off and a possible
outage where some are. It is merged like a schedule from DTEK.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, tzinfo
import logging
import math
import random
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import CALLBACK_TYPE, HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.helpers.event import async_track_point_in_utc_time
from homeassistant.helpers.start import async_at_started
from homeassistant.helpers.storage import Store
from homeassistant.helpers.translation import async_get_translations
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .api import (
    AddressOutage,
    DtekBlockedError,
    DtekClient,
    DtekError,
    Fact,
    House,
    Preset,
    Publication,
    find_house,
    preset_from_dict,
)
from .const import (
    CONF_EXCLUDED_GROUPS,
    CONF_EXTRA_GROUPS,
    CONF_GROUP,
    CONF_GROUP_MANUAL,
    CONF_GROUPS_MODE,
    CONF_HOUSE,
    CONF_LANGUAGE,
    CONF_SETTLEMENT,
    CONF_SHOW_POSSIBLE,
    CONF_STREET,
    CONF_UPDATE_INTERVAL,
    CONF_USE_MIRROR,
    CONF_WARN_END,
    CONF_WARN_START,
    CONNECTION_MIRROR,
    CONNECTION_OFFLINE,
    CONNECTION_OK,
    DATA_CURRENT,
    DATA_STALE,
    DEFAULT_GROUPS_MODE,
    DEFAULT_LANGUAGE,
    DEFAULT_SHOW_POSSIBLE,
    DEFAULT_UPDATE_INTERVAL,
    DEFAULT_USE_MIRROR,
    DOMAIN,
    EVENT_ADDRESS_OUTAGE,
    EVENT_BUS,
    EVENT_GROUP_CHANGED,
    EVENT_GROUPS_CHANGED,
    EVENT_OUTAGE_END_WARNING,
    EVENT_OUTAGE_ENDED,
    EVENT_OUTAGE_STARTED,
    EVENT_OUTAGE_WARNING,
    EVENT_POSSIBLE_OUTAGE_WARNING,
    EVENT_SCHEDULE_CHANGED,
    EVENT_SCHEDULE_PUBLISHED,
    FORCE_UPDATE_FACT,
    GROUP_REMOVAL_UPDATES,
    GROUPS,
    GROUPS_MODE_ALL,
    GROUPS_MODE_MAIN,
    GROUPS_MODES,
    HISTORY_DAYS,
    LANGUAGES,
    MIN_UPDATE_INTERVAL,
    RETRY_JITTER,
    RETRY_MAX_INTERVAL,
    SOURCE_DTEK,
    SOURCE_MIRROR,
    SOURCE_STORAGE,
    STORAGE_SAVE_DELAY,
    STORAGE_VERSION,
    group_name,
    signal_event,
    storage_key,
    warning_thresholds,
)
from .schedule import (
    ALL_ON,
    SLOT_MAYBE,
    SLOT_OFF,
    DayChange,
    Interval,
    combine_days,
    format_intervals,
    future_changes,
    intervals,
    is_valid_slots,
    merge_days,
    outage_minutes,
    slot_at,
    slot_start,
)

_LOGGER = logging.getLogger(__name__)

type DtekConfigEntry = ConfigEntry[DtekCoordinator]


def _isoformat(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None


def _parse_iso(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        return dt_util.parse_datetime(value)
    except ValueError:
        return None


def _parse_days(value: Any) -> dict[date, str]:
    if not isinstance(value, Mapping):
        return {}
    days: dict[date, str] = {}
    for key, slots in value.items():
        try:
            day = date.fromisoformat(key)
        except (TypeError, ValueError):
            continue
        if is_valid_slots(slots):
            days[day] = slots
    return days


def _ordered_groups(groups: Any, skip: set[str] | frozenset[str]) -> list[str]:
    """Return the known groups of a list in UI order, without the ``skip`` ones."""
    if not isinstance(groups, list | tuple):
        return []
    return [group for group in GROUPS if group in groups and group not in skip]


def _days_dict(days: Mapping[date, str], tz: tzinfo) -> dict[str, Any]:
    """Return days as the ``get_schedule`` service gives them."""
    result = {}
    for day, slots in sorted(days.items()):
        outages = intervals({day: slots}, tz)
        result[day.isoformat()] = {
            "outages": [i.as_dict(tz) for i in outages],
            "outages_text": format_intervals(outages, tz),
            "outage_minutes": outage_minutes(slots),
            "possible": [
                i.as_dict(tz) for i in intervals({day: slots}, tz, (SLOT_MAYBE,))
            ],
            "schedule": slots,
        }
    return result


@dataclass(slots=True, kw_only=True)
class DtekData:
    """Snapshot of the state of an entry after an update.

    ``days`` and ``preset`` are what the entities show: the main group, or
    every group followed combined by ``groups_mode``. ``group_days`` and
    ``group_presets`` hold each followed group alone, the main one first.
    """

    group: str
    groups_at_address: list[str] = field(default_factory=list)
    extra_groups: list[str] = field(default_factory=list)
    # The mode in effect: ``main`` while no other group is followed.
    groups_mode: str = GROUPS_MODE_MAIN
    days: dict[date, str] = field(default_factory=dict)
    preset: dict[int, str] = field(default_factory=dict)
    group_days: dict[str, dict[date, str]] = field(default_factory=dict)
    group_presets: dict[str, dict[int, str]] = field(default_factory=dict)
    outages: list[Interval] = field(default_factory=list)
    possible: list[Interval] = field(default_factory=list)
    fact_update: str | None = None
    fact_updated_at: datetime | None = None
    source: str = SOURCE_STORAGE
    address_outage: AddressOutage | None = None
    address_ok: bool = False
    fetch_ok: bool = False
    last_success: datetime | None = None
    last_error: str | None = None
    connection: str = CONNECTION_OFFLINE
    consecutive_failures: int = 0
    last_dtek_success: datetime | None = None
    blocked: bool = False
    publication: Publication = field(default_factory=Publication)
    external_operator: bool = False

    @property
    def combined(self) -> bool:
        """Return True if the entities show several groups together."""
        return self.groups_mode != GROUPS_MODE_MAIN

    @property
    def data_status(self) -> str:
        """Return ``current`` if the last update confirmed the schedule."""
        return DATA_CURRENT if self.fetch_ok else DATA_STALE

    def freshness(self) -> dict[str, Any]:
        """Return the attributes telling how fresh the schedule is."""
        return {
            "data_status": self.data_status,
            "last_verified_at": _isoformat(self.last_success),
        }

    def current_outage(self, now: datetime) -> Interval | None:
        """Return the scheduled outage in progress."""
        return next((i for i in self.outages if i.start <= now < i.end), None)

    def next_outage(self, now: datetime) -> Interval | None:
        """Return the first scheduled outage that has not started yet."""
        return next((i for i in self.outages if i.start > now), None)


class DtekCoordinator(DataUpdateCoordinator[DtekData]):
    """Fetch, merge, store and announce the schedule of one address."""

    config_entry: DtekConfigEntry

    def __init__(
        self, hass: HomeAssistant, entry: DtekConfigEntry, client: DtekClient
    ) -> None:
        """Initialize the coordinator."""
        options = entry.options
        interval = max(
            int(options.get(CONF_UPDATE_INTERVAL, DEFAULT_UPDATE_INTERVAL)),
            MIN_UPDATE_INTERVAL,
        )
        self._base_interval = timedelta(minutes=interval)
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=f"{DOMAIN} {entry.title}",
            update_interval=self._base_interval,
        )
        self.client = client
        self.tz = client.tz
        # None for an entry set up by group only.
        self.settlement: str | None = entry.data.get(CONF_SETTLEMENT)
        self.street: str | None = entry.data.get(CONF_STREET)
        self.house: str | None = entry.data.get(CONF_HOUSE)
        self.has_address = bool(self.settlement and self.street and self.house)
        self.group: str = entry.data[CONF_GROUP]
        self.group_manual: bool = bool(entry.data.get(CONF_GROUP_MANUAL, False))
        self._read_options(options)
        # Entity translations in self.language, keyed like
        # ``component.<domain>.entity.sensor.group.name``.
        self.translations: dict[str, str] = {}
        self._store: Store[dict[str, Any]] = Store(
            hass, STORAGE_VERSION, storage_key(entry.entry_id)
        )
        # What the entities show: the main group, or all groups combined.
        self._days: dict[date, str] = {}
        # The other groups followed: those DTEK lists for the house, or the
        # ones chosen in the options for an entry without an address.
        self._extra_groups: list[str] = (
            []
            if self.has_address
            else _ordered_groups(options.get(CONF_EXTRA_GROUPS), {self.group})
        )
        # Answers in a row without a followed group, until it is dropped.
        self._missing_groups: dict[str, int] = {}
        # Each followed group alone; a group without a key has no schedule yet.
        self._group_days: dict[str, dict[date, str]] = {}
        self._group_presets: dict[str, dict[int, str]] = {}
        # A followed group has no schedule: ask for the whole one, not changes.
        self._full_fact_needed = False
        self._preset_update: str | None = None
        self._fact_update: str | None = None
        self._fact_updated_at: datetime | None = None
        self._source = SOURCE_STORAGE
        self._address_outage: AddressOutage | None = None
        self._address_ok = False
        self._fetch_ok = False
        self._groups_at_address: list[str] = []
        self._house_missing_logged = False
        self._external_operator = False
        self._publication = Publication()
        self._last_success: datetime | None = None
        self._last_dtek_success: datetime | None = None
        self._last_error: str | None = None
        self._connection = CONNECTION_OFFLINE
        self._blocked = False
        # Updates in a row without the main source (DTEK, or the mirror for
        # an entry without an address); they stretch the update interval.
        self._failures = 0
        self._warned: set[str] = set()
        # False until a schedule was recorded once: the first update is silent.
        self._has_baseline = False
        self._outage_now: Interval | None = None
        self._outage_known = False
        self._pending_events: list[tuple[str, dict[str, Any]]] = []
        self._dispatch_enabled = False
        self._unsub_timer: CALLBACK_TYPE | None = None

    def _read_options(self, options: Mapping[str, Any]) -> None:
        """Take the options of the entry; the entry reloads when they change."""
        self.warn_start = tuple(
            timedelta(minutes=m) for m in warning_thresholds(options, CONF_WARN_START)
        )
        self.warn_end = tuple(
            timedelta(minutes=m) for m in warning_thresholds(options, CONF_WARN_END)
        )
        self.use_mirror = bool(options.get(CONF_USE_MIRROR, DEFAULT_USE_MIRROR))
        self.show_possible = bool(
            options.get(CONF_SHOW_POSSIBLE, DEFAULT_SHOW_POSSIBLE)
        )
        mode = options.get(CONF_GROUPS_MODE, DEFAULT_GROUPS_MODE)
        self.groups_mode: str = mode if mode in GROUPS_MODES else DEFAULT_GROUPS_MODE
        self.excluded_groups = frozenset(
            _ordered_groups(options.get(CONF_EXCLUDED_GROUPS), set())
        )
        language = options.get(CONF_LANGUAGE, DEFAULT_LANGUAGE)
        self.language: str = language if language in LANGUAGES else DEFAULT_LANGUAGE

    # -- storage ---------------------------------------------------------

    @property
    def address_key(self) -> str:
        """Return the address the stored state belongs to; empty without one."""
        if not self.has_address:
            return ""
        return f"{self.settlement}|{self.street}|{self.house}"

    @property
    def followed_groups(self) -> list[str]:
        """Return the main group and the other groups followed, main first."""
        return [self.group, *self._extra_groups]

    async def _async_setup(self) -> None:
        """Load the state saved before the last restart.

        A Store written for another address (the entry was reconfigured) is
        ignored. For another group, past days stay as history and the next
        update quietly fetches the schedule of the current group. A Store
        saved before other groups were followed holds the main group only.
        """
        stored = await self._store.async_load()
        if not isinstance(stored, Mapping) or stored.get("address") != self.address_key:
            return
        self._days = _parse_days(stored.get("days"))
        self._last_success = _parse_iso(stored.get("last_success"))
        self._last_dtek_success = _parse_iso(stored.get("last_dtek_success"))
        self._publication = Publication.from_dict(stored.get("publication"))
        self._external_operator = bool(stored.get("external_operator"))
        if stored.get("group") != self.group:
            today, _ = slot_at(dt_util.utcnow(), self.tz)
            self._days = {day: s for day, s in self._days.items() if day <= today}
            return
        self._has_baseline = True
        self._fact_update = stored.get("fact_update")
        self._fact_updated_at = _parse_iso(stored.get("fact_updated_at"))
        self._preset_update = stored.get("preset_update")
        self._address_outage = AddressOutage.from_dict(stored.get("address_outage"))
        groups = stored.get("groups_at_address")
        self._groups_at_address = list(groups) if isinstance(groups, list) else []
        warned = stored.get("warned")
        self._warned = {w for w in warned if isinstance(w, str)} if warned else set()

        if self.has_address:
            # The groups DTEK listed last, and those still kept after DTEK
            # stopped listing them; a group no longer left out in the options
            # is back at once, with no event.
            extra = stored.get("extra_groups")
            self._extra_groups = _ordered_groups(
                [*self._groups_at_address, *(extra if isinstance(extra, list) else [])],
                {self.group, *self.excluded_groups},
            )
        followed = self.followed_groups
        group_days = stored.get("group_days")
        if isinstance(group_days, Mapping):
            self._group_days = {
                group: _parse_days(days)
                for group, days in group_days.items()
                if group in followed
            }
        else:
            self._group_days = {self.group: dict(self._days)}
        presets = stored.get("group_presets")
        if not isinstance(presets, Mapping):
            presets = {self.group: stored.get("preset")}
        self._group_presets = {
            group: preset
            for group, raw in presets.items()
            if group in followed and (preset := preset_from_dict(raw))
        }
        self._full_fact_needed = any(g not in self._group_days for g in followed)
        # The options may have changed what is combined; that is no news.
        self._update_days(dt_util.utcnow(), announce=False)

    def _store_data(self) -> dict[str, Any]:
        return {
            "address": self.address_key,
            "group": self.group,
            "extra_groups": self._extra_groups,
            "fact_update": self._fact_update,
            "fact_updated_at": _isoformat(self._fact_updated_at),
            "preset_update": self._preset_update,
            "days": {day.isoformat(): slots for day, slots in self._days.items()},
            # The main group alone, as 0.1.4 and older read it back.
            "preset": {
                str(day): slots
                for day, slots in self._group_presets.get(self.group, {}).items()
            },
            "group_days": {
                group: {day.isoformat(): slots for day, slots in days.items()}
                for group, days in self._group_days.items()
            },
            "group_presets": {
                group: {str(day): slots for day, slots in preset.items()}
                for group, preset in self._group_presets.items()
            },
            "address_outage": self._address_outage.as_dict()
            if self._address_outage
            else None,
            "groups_at_address": self._groups_at_address,
            "external_operator": self._external_operator,
            "publication": self._publication.as_dict(),
            "warned": sorted(self._warned),
            "last_success": _isoformat(self._last_success),
            "last_dtek_success": _isoformat(self._last_dtek_success),
        }

    # -- update ------------------------------------------------------------

    async def _async_update_data(self) -> DtekData:
        """Fetch the street and schedule, merge and detect changes."""
        now = dt_util.utcnow()
        errors: list[str] = []
        fact: Fact | None = None
        preset: Preset | None = None
        source = SOURCE_DTEK

        dtek_ok = mirror_ok = False
        self._blocked = False
        followed = self.followed_groups
        if self.has_address:
            try:
                fact, preset = await self._async_fetch_dtek()
            except DtekError as err:
                errors.append(f"DTEK: {err}")
                self._address_ok = False
                self._blocked = isinstance(err, DtekBlockedError)
            else:
                dtek_ok = True
                self._last_dtek_success = now

        # Without an address the mirror is the only source, whatever the option.
        if not dtek_ok and (self.use_mirror or not self.has_address):
            try:
                fact, preset = await self._async_fetch_mirror()
            except DtekError as err:
                errors.append(f"mirror: {err}")
            else:
                mirror_ok = True
                source = SOURCE_MIRROR

        self._track_connection(dtek_ok, mirror_ok)
        if not dtek_ok and not mirror_ok and not self._has_baseline:
            raise UpdateFailed(
                translation_domain=DOMAIN,
                translation_key="update_failed",
                translation_placeholders={"error": "; ".join(errors)},
            )

        changed = self._apply_schedule(fact, preset, source, now, from_dtek=dtek_ok)
        # The groups may have changed even without a new schedule.
        changed = self._update_days(now) or changed
        changed = changed or self.followed_groups != followed
        self._fetch_ok = dtek_ok or mirror_ok
        if self._fetch_ok:
            self._last_success = now
        self._last_error = "; ".join(errors) or None
        if not self._has_baseline:
            self._has_baseline = True
            changed = True

        self._prune(now)
        if changed:
            await self._store.async_save(self._store_data())
        else:
            self._store.async_delay_save(self._store_data, STORAGE_SAVE_DELAY)

        self._evaluate(now)
        self._schedule_timer(now)
        return self._snapshot()

    def _apply_schedule(
        self,
        fact: Fact | None,
        preset: Preset | None,
        source: str,
        now: datetime,
        *,
        from_dtek: bool,
    ) -> bool:
        """Take a new schedule for every followed group.

        Returns True if its version changed and needs saving now; the days
        the entities show follow in ``_update_days``.
        """
        changed = False
        if from_dtek and self._publication.daily_hidden:
            changed = self._hide_daily(fact, now)
        elif fact is not None:
            changed = self._apply_fact(fact, source, now)
        if preset is not None:
            for group in self.followed_groups:
                if group_preset := preset.for_group(group):
                    self._group_presets[group] = group_preset
            if self.group in self._group_presets:
                self._preset_update = preset.update
        return changed

    async def _async_fetch_mirror(self) -> tuple[Fact | None, Preset | None]:
        """Return what the mirror has newer than the applied schedule.

        A followed group without a schedule takes the same version too.
        """
        mirror = await self.client.async_get_mirror()
        fact = preset = None
        # The mirror copies the schedule even while DTEK hides it.
        if (
            mirror.fact is not None
            and not self._publication.daily_hidden
            and self._is_newer(mirror.fact, same=self._full_fact_needed)
        ):
            fact = mirror.fact
        if mirror.preset is not None and (
            any(g not in self._group_presets for g in self.followed_groups)
            or mirror.preset.update != self._preset_update
        ):
            preset = mirror.preset
        return fact, preset

    def _track_connection(self, dtek_ok: bool, mirror_ok: bool) -> None:
        """Record what answered and stretch the interval after failures."""
        main_ok = dtek_ok if self.has_address else mirror_ok
        self._failures = 0 if main_ok else self._failures + 1
        self.update_interval = self._next_interval()
        if dtek_ok:
            self._connection = CONNECTION_OK
        elif mirror_ok:
            self._connection = CONNECTION_MIRROR
        else:
            self._connection = CONNECTION_OFFLINE

    def _next_interval(self) -> timedelta:
        """Return the update interval, doubled for every failed update in a row.

        It grows up to RETRY_MAX_INTERVAL minutes (or the configured interval
        if longer) with jitter, and is back to normal after a success.
        """
        if not self._failures:
            return self._base_interval
        longest = max(self._base_interval, timedelta(minutes=RETRY_MAX_INTERVAL))
        delay = min(self._base_interval * 2 ** min(self._failures - 1, 8), longest)
        return delay * random.uniform(1 - RETRY_JITTER, 1 + RETRY_JITTER)  # noqa: S311

    async def _async_fetch_dtek(self) -> tuple[Fact | None, Preset | None]:
        """Ask DTEK for the street; follow the groups of the house."""
        settlement, street_name = self.settlement or "", self.street or ""
        version = self._fact_update
        if self._full_fact_needed or not version:
            version = FORCE_UPDATE_FACT
        street = await self.client.async_get_street(settlement, street_name, version)
        self._address_ok = True
        was_hidden = self._publication.daily_hidden
        self._publication = street.publication
        self._apply_house(find_house(street.houses, self.house or ""))
        # A new group needs the whole schedule, not only changes; so do the
        # days cleared while the schedule was hidden, once it is shown again.
        # A request that already asked for the whole one is not repeated.
        shown_again = was_hidden and not self._publication.daily_hidden
        if (
            street.fact is None
            and version != FORCE_UPDATE_FACT
            and (self._full_fact_needed or shown_again)
        ):
            street = await self.client.async_get_street(
                settlement, street_name, FORCE_UPDATE_FACT
            )
            self._publication = street.publication
        return street.fact, street.preset

    def _is_newer(self, fact: Fact, *, same: bool = False) -> bool:
        """Return True if a mirror schedule is newer than the applied one.

        With ``same``, the applied version itself counts too.
        """
        if fact.update is None:
            return False
        if fact.update == self._fact_update:
            return same
        if fact.updated_at is not None and self._fact_updated_at is not None:
            return fact.updated_at > self._fact_updated_at
        return True

    def _apply_fact(self, fact: Fact, source: str, now: datetime) -> bool:
        """Merge a schedule into every followed group; True for a new version."""
        today, current_slot = slot_at(now, self.tz)
        for group in self.followed_groups:
            self._group_days[group] = merge_days(
                self._group_days.get(group, {}),
                fact.for_group(group),
                today,
                current_slot,
            )
        version_changed = fact.update != self._fact_update
        self._fact_update = fact.update
        self._fact_updated_at = fact.updated_at
        self._source = source
        self._full_fact_needed = False
        return version_changed

    def _hide_daily(self, fact: Fact | None, now: datetime) -> bool:
        """Clear the schedule from now on while DTEK hides it.

        The DTEK page doesn't show the schedule then, so the entities don't
        either; finished slots stay as history. The version is still recorded,
        the schedule is asked for again once it is shown.
        """
        today, current_slot = slot_at(now, self.tz)
        for group, days in self._group_days.items():
            cleared = {day: ALL_ON for day in days if day >= today}
            self._group_days[group] = merge_days(days, cleared, today, current_slot)
        version_changed = False
        if fact is not None:
            version_changed = fact.update != self._fact_update
            self._fact_update = fact.update
            self._fact_updated_at = fact.updated_at
            self._source = SOURCE_DTEK
            self._full_fact_needed = False
        return version_changed

    def _mode(self) -> str:
        """Return the groups mode in effect: the main group alone without others."""
        return self.groups_mode if self._extra_groups else GROUPS_MODE_MAIN

    def _target_days(self) -> dict[date, str]:
        """Return the schedule the entities follow, before the merge."""
        if (mode := self._mode()) == GROUPS_MODE_MAIN:
            return dict(self._group_days.get(self.group, {}))
        return combine_days(
            (self._group_days.get(g, {}) for g in self.followed_groups),
            every=mode == GROUPS_MODE_ALL,
        )

    def _target_preset(self) -> dict[int, str]:
        """Return the weekly schedule the calendar shows."""
        if (mode := self._mode()) == GROUPS_MODE_MAIN:
            return dict(self._group_presets.get(self.group, {}))
        return combine_days(
            (self._group_presets.get(g, {}) for g in self.followed_groups),
            every=mode == GROUPS_MODE_ALL,
        )

    def groups_off(self, now: datetime) -> list[str]:
        """Return the followed groups whose own schedule has an outage now."""
        day, index = slot_at(now, self.tz)
        return [
            group
            for group in self.followed_groups
            if (slots := self._group_days.get(group, {}).get(day)) is not None
            and slots[index] == SLOT_OFF
        ]

    def groups_in(self, interval: Interval) -> list[str]:
        """Return the groups with an outage or possible outage in ``interval``.

        Only the groups the schedule of the entities follows: the main group
        alone, or every followed group when they are combined.
        """
        if self._mode() == GROUPS_MODE_MAIN:
            return [self.group]
        return [
            group
            for group in self.followed_groups
            if any(
                item.start < interval.end and interval.start < item.end
                for item in intervals(
                    self._group_days.get(group, {}), self.tz, (SLOT_OFF, SLOT_MAYBE)
                )
            )
        ]

    def _update_days(self, now: datetime, *, announce: bool = True) -> bool:
        """Merge the schedule of the groups into the days the entities show.

        What already happened stays as it was. Days ahead that none of the
        groups has any more (a group was dropped) are dropped too. Returns
        True if the future changed; events are queued for it.
        """
        today, current_slot = slot_at(now, self.tz)
        target = self._target_days()
        merged = {
            day: slots
            for day, slots in merge_days(
                self._days, target, today, current_slot
            ).items()
            if day <= today or day in target
        }
        changes = (
            future_changes(self._days, merged, today, current_slot)
            if self._has_baseline and announce
            else []
        )
        self._days = merged
        for change in changes:
            self._queue_schedule_event(change, today)
        return bool(changes)

    def _apply_house(self, house: House | None) -> None:
        """Take the groups and the outage of the address."""
        if house is None:
            if not self._house_missing_logged:
                _LOGGER.warning(
                    "%s: house %s is not listed by DTEK for %s, %s any more",
                    self.config_entry.title,
                    self.house,
                    self.settlement,
                    self.street,
                )
                self._house_missing_logged = True
            groups: list[str] = []
            outage = None
            external = False
        else:
            self._house_missing_logged = False
            groups = house.groups
            # The page leaves the outage of the house out when told so.
            outage = (
                house.outage if self._publication.current_outage is not False else None
            )
            external = house.external

        if external and not self._external_operator:
            _LOGGER.warning(
                "%s: DTEK says house %s is served by another operator; "
                "the DTEK schedule may not apply to it",
                self.config_entry.title,
                self.house,
            )
        self._external_operator = external
        self._update_address_outage(outage)
        # A missing house or an empty list is not taken as the house losing
        # its groups: the groups known stay.
        if not groups:
            return
        self._groups_at_address = list(groups)

        previous_main, previous_extra = self.group, list(self._extra_groups)
        self._follow_main_group(groups)
        self._follow_extra_groups(groups)
        followed = self.followed_groups
        self._group_days = {g: d for g, d in self._group_days.items() if g in followed}
        self._group_presets = {
            g: p for g, p in self._group_presets.items() if g in followed
        }
        if any(g not in self._group_days for g in followed):
            self._full_fact_needed = True

        # The main group moving in or out of the other groups is no news.
        added = [
            g for g in self._extra_groups if g not in [*previous_extra, previous_main]
        ]
        removed = [
            g for g in previous_extra if g not in [*self._extra_groups, self.group]
        ]
        if not added and not removed:
            return
        _LOGGER.info(
            "%s: other groups of the address are now %s (added %s, removed %s)",
            self.config_entry.title,
            self._extra_groups,
            added,
            removed,
        )
        if self._has_baseline:
            self._queue(
                EVENT_GROUPS_CHANGED,
                {
                    "added": [group_name(g) for g in added],
                    "removed": [group_name(g) for g in removed],
                    "extra_groups": [group_name(g) for g in self._extra_groups],
                },
            )

    def _follow_extra_groups(self, groups: list[str]) -> None:
        """Follow the other groups DTEK lists for the house.

        A new group is taken at once. A group no longer listed stays for
        GROUP_REMOVAL_UPDATES answers in a row without it, so a passing glitch
        of DTEK adds and removes nothing.
        """
        listed = _ordered_groups(groups, {self.group, *self.excluded_groups})
        kept: list[str] = []
        for group in self._extra_groups:
            if group in listed or group == self.group:
                continue
            misses = self._missing_groups.get(group, 0) + 1
            if misses < GROUP_REMOVAL_UPDATES:
                self._missing_groups[group] = misses
                kept.append(group)
        self._missing_groups = {
            g: misses for g, misses in self._missing_groups.items() if g in kept
        }
        self._extra_groups = _ordered_groups([*listed, *kept], {self.group})

    def _follow_main_group(self, groups: list[str]) -> None:
        """Move to the group DTEK lists when it is the only one.

        A group chosen by the user is never replaced.
        """
        if self.group_manual or len(groups) != 1 or groups[0] == self.group:
            return
        previous, self.group = self.group, groups[0]
        _LOGGER.info(
            "%s: DTEK moved the address from group %s to %s",
            self.config_entry.title,
            previous,
            self.group,
        )
        self.hass.config_entries.async_update_entry(
            self.config_entry, data={**self.config_entry.data, CONF_GROUP: self.group}
        )
        # Today keeps its past; the days ahead belonged to the old group.
        today, _ = slot_at(dt_util.utcnow(), self.tz)
        self._days = {day: s for day, s in self._days.items() if day <= today}
        self._fact_update = None
        self._fact_updated_at = None
        self._preset_update = None
        self._full_fact_needed = True
        self._queue(
            EVENT_GROUP_CHANGED,
            {"previous_group": previous, "previous_group_name": group_name(previous)},
        )

    def _update_address_outage(self, outage: AddressOutage | None) -> None:
        old, self._address_outage = self._address_outage, outage
        if not self._has_baseline or old == outage:
            return
        if outage is None:
            status = "cleared"
        elif old is None or (old.reason, old.start) != (outage.reason, outage.start):
            status = "new"
        else:
            status = "updated"
        shown = outage or old
        self._queue(
            EVENT_ADDRESS_OUTAGE,
            {
                "status": status,
                "reason": shown.reason if shown else None,
                "kind": shown.kind if shown else None,
                "start": _isoformat(shown.start) if shown else None,
                "end": _isoformat(shown.end) if shown else None,
                "previous_end": _isoformat(old.end) if old else None,
            },
        )

    def _prune(self, now: datetime) -> None:
        today, _ = slot_at(now, self.tz)
        oldest = today - timedelta(days=HISTORY_DAYS)
        self._days = {day: s for day, s in self._days.items() if day >= oldest}
        self._group_days = {
            group: {day: s for day, s in days.items() if day >= oldest}
            for group, days in self._group_days.items()
        }
        cutoff = now - timedelta(days=1)
        # Keys are ``<kind>@<minutes>@<moment>``; older ones are the bare moment.
        self._warned = {
            w
            for w in self._warned
            if (moment := _parse_iso(w.rsplit("@", 1)[-1])) and moment > cutoff
        }

    def _snapshot(self) -> DtekData:
        followed = self.followed_groups
        return DtekData(
            group=self.group,
            groups_at_address=list(self._groups_at_address),
            extra_groups=list(self._extra_groups),
            groups_mode=self._mode(),
            days=dict(self._days),
            preset=self._target_preset(),
            group_days={g: dict(self._group_days.get(g, {})) for g in followed},
            group_presets={g: dict(self._group_presets.get(g, {})) for g in followed},
            outages=intervals(self._days, self.tz),
            possible=intervals(self._days, self.tz, (SLOT_MAYBE,)),
            fact_update=self._fact_update,
            fact_updated_at=self._fact_updated_at,
            source=self._source,
            address_outage=self._address_outage,
            address_ok=self._address_ok,
            fetch_ok=self._fetch_ok,
            last_success=self._last_success,
            last_error=self._last_error,
            connection=self._connection,
            consecutive_failures=self._failures,
            last_dtek_success=self._last_dtek_success,
            blocked=self._blocked,
            publication=self._publication,
            external_operator=self._external_operator,
        )

    # -- time based events -----------------------------------------------

    @callback
    def _evaluate(self, now: datetime) -> None:
        """Queue started/ended events and warnings due at ``now``."""
        outages = intervals(self._days, self.tz)
        current = next((i for i in outages if i.start <= now < i.end), None)
        if self._outage_known:
            # An outage is identified by its start: finished slots never
            # change, so a longer or shorter outage keeps its start.
            previous = self._outage_now
            current_start = current.start if current else None
            previous_start = previous.start if previous else None
            if previous is not None and previous_start != current_start:
                upcoming = next((i for i in outages if i.start > now), None)
                self._queue(
                    EVENT_OUTAGE_ENDED,
                    {
                        **self._interval_data(previous),
                        "next_start": _isoformat(upcoming.start.astimezone(self.tz))
                        if upcoming
                        else None,
                        "next_end": _isoformat(upcoming.end.astimezone(self.tz))
                        if upcoming
                        else None,
                    },
                )
            if current is not None and previous_start != current_start:
                self._queue(EVENT_OUTAGE_STARTED, self._interval_data(current))
        self._outage_now = current
        self._outage_known = True

        for outage in outages:
            if outage.start > now:
                self._warn(
                    now,
                    outage,
                    "start",
                    outage.start,
                    thresholds=self.warn_start,
                    event_type=EVENT_OUTAGE_WARNING,
                )
            elif outage.start <= now < outage.end:
                # A threshold at least as long as the outage would fire the
                # "ending" warning together with the start.
                ends = tuple(t for t in self.warn_end if outage.end - t > outage.start)
                self._warn(
                    now,
                    outage,
                    "end",
                    outage.end,
                    thresholds=ends,
                    event_type=EVENT_OUTAGE_END_WARNING,
                )
        for possible in self._possible_outages():
            if possible.start > now:
                self._warn(
                    now,
                    possible,
                    "possible",
                    possible.start,
                    thresholds=self.warn_start,
                    event_type=EVENT_POSSIBLE_OUTAGE_WARNING,
                )

    def _possible_outages(self) -> list[Interval]:
        """Return the possible outages that start while the power is on.

        One that follows an outage straight away gets no warning: the power is
        off already.
        """
        items = intervals(self._days, self.tz, (SLOT_OFF, SLOT_MAYBE))
        return [
            item
            for index, item in enumerate(items)
            if item.kind == SLOT_MAYBE
            and (index == 0 or items[index - 1].end != item.start)
        ]

    def _warn(
        self,
        now: datetime,
        outage: Interval,
        kind: str,
        moment: datetime,
        *,
        thresholds: tuple[timedelta, ...],
        event_type: str,
    ) -> None:
        """Queue one warning for the thresholds of ``moment`` that are now due.

        Several due thresholds (a new outage that starts sooner than all of
        them) give a single event and are all marked as sent.
        """
        due = [t for t in thresholds if moment - t <= now]
        keys = {
            f"{kind}@{int(t.total_seconds() // 60)}@{moment.isoformat()}"  # UTC
            for t in due
        }
        if not keys or keys <= self._warned:
            return
        self._warned |= keys
        self._store.async_delay_save(self._store_data, STORAGE_SAVE_DELAY)
        self._queue(
            event_type,
            {
                **self._interval_data(outage),
                "minutes": math.ceil((moment - now).total_seconds() / 60),
            },
        )

    @callback
    def _schedule_timer(self, now: datetime) -> None:
        """Wake up at the next outage edge, warning or local midnight."""
        self._cancel_timer()
        moments: list[datetime] = []
        for outage in intervals(self._days, self.tz):
            moments.extend((outage.start, outage.end))
            moments.extend(outage.start - t for t in self.warn_start)
            moments.extend(
                outage.end - t for t in self.warn_end if outage.end - t > outage.start
            )
        for possible in self._possible_outages():
            moments.extend(possible.start - t for t in self.warn_start)
        # The groups status sensor switches at the edges of every group.
        for days in self._group_days.values():
            for item in intervals(days, self.tz):
                moments.extend((item.start, item.end))
        if (address := self._address_outage) is not None:
            moments.extend(m for m in (address.start, address.end) if m is not None)
        today, _ = slot_at(now, self.tz)
        moments.append(slot_start(today, 48, self.tz))
        if future := [m for m in moments if m > now]:
            self._unsub_timer = async_track_point_in_utc_time(
                self.hass, self._handle_timer, min(future)
            )

    @callback
    def _handle_timer(self, _now: datetime) -> None:
        self._unsub_timer = None
        now = dt_util.utcnow()
        self._evaluate(now)
        self._schedule_timer(now)
        if self.data is not None:
            self.async_update_listeners()

    @callback
    def _cancel_timer(self) -> None:
        if self._unsub_timer is not None:
            self._unsub_timer()
            self._unsub_timer = None

    async def async_load_translations(self) -> None:
        """Load the entity names in the language chosen for the entry."""
        self.translations = await async_get_translations(
            self.hass, self.language, "entity", {DOMAIN}
        )

    async def async_shutdown(self) -> None:
        """Cancel the timer, write the state now and stop polling.

        Writing now replaces a pending delayed save, which would otherwise
        recreate the file after ``async_remove_entry`` deleted it.
        """
        self._cancel_timer()
        if self._has_baseline:
            await self._store.async_save(self._store_data())
        await super().async_shutdown()

    # -- events ------------------------------------------------------------

    def _interval_data(self, interval: Interval) -> dict[str, Any]:
        return {
            **interval.as_dict(self.tz),
            "duration_minutes": interval.minutes,
            "groups": [group_name(g) for g in self.groups_in(interval)],
        }

    def _queue_schedule_event(self, change: DayChange, today: date) -> None:
        day_slots = {change.day: change.current}
        outages = intervals(day_slots, self.tz)
        if change.day == today:
            relative = "today"
        elif change.day == today + timedelta(days=1):
            relative = "tomorrow"
        else:
            relative = "other"
        data: dict[str, Any] = {
            "date": change.day.isoformat(),
            "day": relative,
            "outages": [i.as_dict(self.tz) for i in outages],
            "outages_text": format_intervals(outages, self.tz),
            "outage_minutes": outage_minutes(change.current),
            "possible": [
                i.as_dict(self.tz) for i in intervals(day_slots, self.tz, (SLOT_MAYBE,))
            ],
            "schedule": change.current,
            "schedule_updated": _isoformat(self._fact_updated_at),
            "source": self._source,
        }
        if change.previous is not None:
            previous = intervals({change.day: change.previous}, self.tz)
            data["previous_outages"] = [i.as_dict(self.tz) for i in previous]
            data["previous_outages_text"] = format_intervals(previous, self.tz)
            data["previous_outage_minutes"] = outage_minutes(change.previous)
        self._queue(
            EVENT_SCHEDULE_PUBLISHED if change.published else EVENT_SCHEDULE_CHANGED,
            data,
        )

    def _queue(self, event_type: str, data: dict[str, Any]) -> None:
        self._pending_events.append(
            (
                event_type,
                {
                    **data,
                    "type": event_type,
                    "group": self.group,
                    "group_name": group_name(self.group),
                    "settlement": self.settlement,
                    "street": self.street,
                    "house": self.house,
                    "config_entry_id": self.config_entry.entry_id,
                    "entry_title": self.config_entry.title,
                },
            )
        )

    @callback
    def async_update_listeners(self) -> None:
        """Update entities first, then send the queued events."""
        super().async_update_listeners()
        self._async_dispatch()

    @callback
    def async_enable_event_dispatch(self) -> CALLBACK_TYPE:
        """Start sending events once Home Assistant has started.

        Automations attach their triggers on ``homeassistant_started``; events
        found while starting are queued until then instead of being lost.
        """

        @callback
        def _started(_hass: HomeAssistant) -> None:
            self._dispatch_enabled = True
            self._async_dispatch()

        return async_at_started(self.hass, _started)

    @callback
    def _async_dispatch(self) -> None:
        if not self._dispatch_enabled or not self._pending_events:
            return
        pending, self._pending_events = self._pending_events, []
        signal = signal_event(self.config_entry.entry_id)
        for event_type, payload in pending:
            _LOGGER.debug("%s: %s %s", self.config_entry.title, event_type, payload)
            self.hass.bus.async_fire(EVENT_BUS, payload)
            async_dispatcher_send(self.hass, signal, event_type, payload)

    # -- service helpers ---------------------------------------------------

    def schedule_dict(self) -> dict[str, Any]:
        """Return the full state for the ``get_schedule`` service.

        ``days`` and ``weekly`` are what the entities show; ``groups`` has
        every followed group alone.
        """
        data = self.data
        return {
            "config_entry_id": self.config_entry.entry_id,
            "title": self.config_entry.title,
            "settlement": self.settlement,
            "street": self.street,
            "house": self.house,
            "group": data.group,
            "group_name": group_name(data.group),
            "groups_at_address": data.groups_at_address,
            "extra_groups": data.extra_groups,
            "groups_mode": data.groups_mode,
            "external_operator": data.external_operator,
            "schedule_updated": _isoformat(data.fact_updated_at),
            "source": data.source,
            "connection": data.connection,
            "data_status": data.data_status,
            "publication": data.publication.as_dict(),
            "last_success": _isoformat(data.last_success),
            "last_dtek_success": _isoformat(data.last_dtek_success),
            "last_error": data.last_error,
            "days": _days_dict(data.days, self.tz),
            "weekly": {str(day): slots for day, slots in sorted(data.preset.items())},
            "groups": {
                group: {
                    "group_name": group_name(group),
                    "days": _days_dict(days, self.tz),
                    "weekly": {
                        str(day): slots
                        for day, slots in sorted(
                            data.group_presets.get(group, {}).items()
                        )
                    },
                }
                for group, days in data.group_days.items()
            },
            "address_outage": data.address_outage.as_dict()
            if data.address_outage
            else None,
        }


async def async_remove_store(hass: HomeAssistant, entry_id: str) -> None:
    """Delete the stored state of an entry."""
    await Store[dict[str, Any]](
        hass, STORAGE_VERSION, storage_key(entry_id)
    ).async_remove()
