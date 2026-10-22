"""Half-hour schedule model used by the parser, the coordinator and entities.

DTEK describes a day with 24 hourly values, ``"1"`` being 00:00-01:00 and
``"24"`` 23:00-24:00 local time (verified 2026-10-18)::

    yes      power on
    no       outage
    first    outage during the first 30 minutes
    second   outage during the second 30 minutes
    maybe    possible outage (weekly schedule)
    mfirst   possible outage during the first 30 minutes
    msecond  possible outage during the second 30 minutes

A day is kept as a 48 character string, one character per half hour:
``1`` power on, ``0`` outage, ``?`` possible outage. Strings are cheap to
store, compare and slice, which is all the merge logic needs. Schedules of
several groups combine slot by slot: into the worst of them, or into an outage
only where all of them are off and a possible outage where some are.
"""

from __future__ import annotations

from collections.abc import Container, Iterable, Mapping
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta, tzinfo
from typing import Any

SLOT_ON = "1"
SLOT_OFF = "0"
SLOT_MAYBE = "?"
SLOTS_PER_DAY = 48
SLOT_MINUTES = 30
ALL_ON = SLOT_ON * SLOTS_PER_DAY

_HOUR_VALUES: dict[str, str] = {
    "yes": SLOT_ON * 2,
    "no": SLOT_OFF * 2,
    "first": SLOT_OFF + SLOT_ON,
    "second": SLOT_ON + SLOT_OFF,
    "maybe": SLOT_MAYBE * 2,
    "mfirst": SLOT_MAYBE + SLOT_ON,
    "msecond": SLOT_ON + SLOT_MAYBE,
}


def parse_hours(hours: Any) -> str | None:
    """Convert ``{"1": "yes", ..., "24": "no"}`` to 48 slots.

    Unknown or missing values become possible outages rather than a guess
    either way. Returns None when not a single hour is understood.
    """
    if not isinstance(hours, Mapping):
        return None
    parts: list[str] = []
    known = 0
    for hour in range(1, 25):
        value = hours.get(str(hour))
        pair = _HOUR_VALUES.get(value) if isinstance(value, str) else None
        if pair is None:
            pair = SLOT_MAYBE * 2
        else:
            known += 1
        parts.append(pair)
    return "".join(parts) if known else None


def is_valid_slots(value: Any) -> bool:
    """Return True for a well formed 48 slot string."""
    return (
        isinstance(value, str)
        and len(value) == SLOTS_PER_DAY
        and set(value) <= {SLOT_ON, SLOT_OFF, SLOT_MAYBE}
    )


def slot_start(day: date, index: int, tz: tzinfo) -> datetime:
    """Return the wall-clock start of slot ``index``; 48 is the next midnight."""
    day += timedelta(days=index // SLOTS_PER_DAY)
    index %= SLOTS_PER_DAY
    return datetime(
        day.year, day.month, day.day, index // 2, SLOT_MINUTES * (index % 2), tzinfo=tz
    )


def _exists(moment: datetime) -> bool:
    """Return False for wall times skipped by a DST change."""
    round_trip = moment.astimezone(UTC).astimezone(moment.tzinfo)
    return round_trip.replace(tzinfo=None) == moment.replace(tzinfo=None)


def slot_at(moment: datetime, tz: tzinfo) -> tuple[date, int]:
    """Return the local day and slot index containing ``moment``."""
    local = moment.astimezone(tz)
    return local.date(), local.hour * 2 + local.minute // SLOT_MINUTES


@dataclass(frozen=True, slots=True)
class Interval:
    """A run of slots of one kind (outage or possible outage).

    Start and end are in UTC: Python compares and subtracts datetimes that
    share a ``tzinfo`` by wall time, which is wrong across a DST change.
    """

    start: datetime
    end: datetime
    kind: str = SLOT_OFF

    @property
    def minutes(self) -> int:
        """Return the length in minutes."""
        return int((self.end - self.start).total_seconds() // 60)

    def as_dict(self, tz: tzinfo | None = None) -> dict[str, Any]:
        """Return start and end in ISO format, in ``tz`` if given."""
        start, end = self.start, self.end
        if tz is not None:
            start, end = start.astimezone(tz), end.astimezone(tz)
        return {"start": start.isoformat(), "end": end.isoformat()}


def intervals(
    days: Mapping[date, str],
    tz: tzinfo,
    kinds: Container[str] = (SLOT_OFF,),
) -> list[Interval]:
    """Return the runs of the given slot kinds, joined across midnight."""
    result: list[Interval] = []
    for day in sorted(days):
        slots = days[day]
        for index, char in enumerate(slots):
            if char not in kinds:
                continue
            start = slot_start(day, index, tz)
            if not _exists(start):
                continue
            start = start.astimezone(UTC)
            end = slot_start(day, index + 1, tz).astimezone(UTC)
            if end <= start:
                continue
            last = result[-1] if result else None
            if last is not None and last.kind == char and last.end == start:
                result[-1] = Interval(last.start, end, char)
            else:
                result.append(Interval(start, end, char))
    return result


def format_intervals(items: Iterable[Interval], tz: tzinfo) -> str:
    """Format intervals as ``08:00–12:00, 22:00–24:00``."""
    parts = []
    for item in items:
        start = item.start.astimezone(tz)
        end = item.end.astimezone(tz)
        end_text = end.strftime("%H:%M")
        if end_text == "00:00" and end.date() == start.date() + timedelta(days=1):
            end_text = "24:00"
        parts.append(f"{start:%H:%M}–{end_text}")
    return ", ".join(parts)


def outage_minutes(slots: str) -> int:
    """Return the scheduled outage time of a day in minutes."""
    return slots.count(SLOT_OFF) * SLOT_MINUTES


def merge_days(
    stored: Mapping[date, str],
    incoming: Mapping[date, str],
    today: date,
    current_slot: int,
) -> dict[date, str]:
    """Combine the stored schedule with a newer one.

    What already happened stays as it was: past days and the finished slots
    of today keep their stored values. The current slot and everything after
    it follow the new data. Days missing from the new data are kept, since
    DTEK only lists the days it has published.
    """
    merged: dict[date, str] = {}
    for day in sorted(set(stored) | set(incoming)):
        old, new = stored.get(day), incoming.get(day)
        if new is None or (old is not None and day < today):
            merged[day] = old  # type: ignore[assignment]
        elif old is not None and day == today:
            merged[day] = old[:current_slot] + new[current_slot:]
        else:
            merged[day] = new
    return merged


def _combine_slot(chars: tuple[str, ...], every: bool) -> str:
    if SLOT_OFF in chars and not (every and any(c != SLOT_OFF for c in chars)):
        return SLOT_OFF
    if SLOT_OFF in chars or SLOT_MAYBE in chars:
        return SLOT_MAYBE
    return SLOT_ON


def combine_slots(values: Iterable[str], *, every: bool = False) -> str:
    """Return several schedules of one day as one, slot by slot.

    An outage in any of them is an outage. With ``every``, an outage needs all
    of them off, and an outage in only some of them is a possible outage.
    Otherwise a possible outage in any of them is a possible outage.
    """
    return "".join(_combine_slot(chars, every) for chars in zip(*values, strict=True))


def combine_days[K: (date, int)](
    schedules: Iterable[Mapping[K, str]], *, every: bool = False
) -> dict[K, str]:
    """Combine the schedules of several groups day by day (or weekday).

    A day missing from some of them counts as power on there: the worst of
    the others stays as it is, and with ``every`` an outage of all the others
    is only a possible outage, since nothing says the missing ones are off.
    """
    groups = list(schedules)
    days = sorted({day for group in groups for day in group})
    return {
        day: combine_slots([group.get(day, ALL_ON) for group in groups], every=every)
        for day in days
    }


@dataclass(frozen=True, slots=True)
class DayChange:
    """The future part of a day differs between two schedules."""

    day: date
    previous: str | None
    current: str

    @property
    def published(self) -> bool:
        """Return True if the day had no schedule before."""
        return self.previous is None


def future_changes(
    old: Mapping[date, str],
    new: Mapping[date, str],
    today: date,
    current_slot: int,
) -> list[DayChange]:
    """Return the days whose schedule changed from the current slot on."""
    changes: list[DayChange] = []
    for day in sorted(new):
        if day < today:
            continue
        before, after = old.get(day), new[day]
        start = current_slot if day == today else 0
        if before is None or before[start:] != after[start:]:
            changes.append(DayChange(day, before, after))
    return changes


def possible_days(
    preset: Mapping[int, str], first_day: date, count: int, skip: Container[date]
) -> dict[date, str]:
    """Return the weekly schedule for ``count`` days, every outage as possible.

    ``preset`` maps ISO weekdays (1 = Monday) to slots; days in ``skip``
    already have an actual schedule.
    """
    days: dict[date, str] = {}
    for offset in range(count):
        day = first_day + timedelta(days=offset)
        slots = preset.get(day.isoweekday())
        if day in skip or slots is None:
            continue
        days[day] = "".join(
            SLOT_ON if char == SLOT_ON else SLOT_MAYBE for char in slots
        )
    return days
