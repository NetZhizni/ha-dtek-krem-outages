"""Tests for the half-hour schedule model."""

from __future__ import annotations

from datetime import date, timedelta

from custom_components.dtek_krem_outages.schedule import (
    ALL_ON,
    Interval,
    combine_days,
    combine_slots,
    format_intervals,
    future_changes,
    intervals,
    is_valid_slots,
    merge_days,
    outage_minutes,
    parse_hours,
    possible_days,
    slot_at,
)

from .conftest import KYIV, TODAY, TOMORROW, hours_from_slots, kyiv, slots


def test_parse_hours_all_values() -> None:
    """Every DTEK value maps to two half-hour slots."""
    hours = {str(h): "yes" for h in range(1, 25)}
    hours.update(
        {
            "1": "no",
            "2": "first",
            "3": "second",
            "4": "maybe",
            "5": "mfirst",
            "6": "msecond",
        }
    )
    assert parse_hours(hours) == "00" + "01" + "10" + "??" + "?1" + "1?" + "1" * 36


def test_parse_hours_unknown_values() -> None:
    """Unknown or missing hours become possible outages; nothing known is None."""
    assert parse_hours({"1": "no", "2": "later"})[:6] == "00????"
    assert parse_hours({"1": "unknown"}) is None
    assert parse_hours([]) is None
    assert parse_hours(None) is None


def test_round_trip_helpers() -> None:
    """The test helpers build what the parser reads."""
    value = slots(("08:00", "09:30"), possible=(("20:00", "21:00"),))
    assert parse_hours(hours_from_slots(value)) == value
    assert is_valid_slots(value)
    assert not is_valid_slots(value[:-1])
    assert not is_valid_slots("x" * 48)


def test_slot_at() -> None:
    """The slot index follows the Kyiv wall clock."""
    assert slot_at(kyiv(TODAY, "00:00"), KYIV) == (TODAY, 0)
    assert slot_at(kyiv(TODAY, "10:29"), KYIV) == (TODAY, 20)
    assert slot_at(kyiv(TODAY, "23:45"), KYIV) == (TODAY, 47)


def test_intervals_join_across_midnight() -> None:
    """Runs are merged, also from one day into the next."""
    days = {
        TODAY: slots(("08:00", "10:00"), ("22:00", "24:00")),
        TOMORROW: slots(("00:00", "02:00"), possible=(("12:00", "13:00"),)),
    }
    result = intervals(days, KYIV)
    assert result == [
        Interval(kyiv(TODAY, "08:00"), kyiv(TODAY, "10:00")),
        Interval(kyiv(TODAY, "22:00"), kyiv(TOMORROW, "02:00")),
    ]
    assert result[1].minutes == 240
    possible = intervals(days, KYIV, ("?",))
    assert possible == [Interval(kyiv(TOMORROW, "12:00"), kyiv(TOMORROW, "13:00"), "?")]


def test_intervals_skip_gaps_between_days() -> None:
    """Days that are not adjacent are not joined."""
    later = TODAY + timedelta(days=2)
    days = {TODAY: slots(("23:00", "24:00")), later: slots(("00:00", "01:00"))}
    assert len(intervals(days, KYIV)) == 2


def test_intervals_dst_spring_forward() -> None:
    """On the day 03:00 does not exist, its slots are dropped."""
    day = date(2027, 3, 28)
    result = intervals({day: slots(("02:00", "05:00"))}, KYIV)
    assert len(result) == 1
    assert result[0].start == kyiv(day, "02:00")
    assert result[0].end == kyiv(day, "05:00")
    assert result[0].minutes == 120


def test_format_intervals() -> None:
    """Intervals are printed in local time, a day end as 24:00."""
    days = {TODAY: slots(("08:00", "12:30"), ("22:00", "24:00"))}
    assert format_intervals(intervals(days, KYIV), KYIV) == "08:00–12:30, 22:00–24:00"
    cross = {TODAY: slots(("23:00", "24:00")), TOMORROW: slots(("00:00", "01:00"))}
    assert format_intervals(intervals(cross, KYIV), KYIV) == "23:00–01:00"
    assert format_intervals([], KYIV) == ""


def test_outage_minutes() -> None:
    """Possible outages are not counted."""
    assert (
        outage_minutes(slots(("08:00", "09:30"), possible=(("10:00", "11:00"),))) == 90
    )


def test_merge_keeps_past_and_takes_future() -> None:
    """Finished slots keep their stored value, the rest follows the new data."""
    yesterday = TODAY - timedelta(days=1)
    stored = {
        yesterday: slots(("10:00", "12:00")),
        TODAY: slots(("08:00", "10:00"), ("16:00", "18:00")),
    }
    incoming = {
        yesterday: slots(("00:00", "24:00")),  # rewriting history is ignored
        TODAY: slots(("09:00", "11:00"), ("19:00", "20:00")),
        TOMORROW: slots(("06:00", "07:00")),
    }
    # 10:10: slots before 10:00 are finished, 10:00-10:30 is in progress.
    merged = merge_days(stored, incoming, TODAY, 20)
    assert merged[yesterday] == stored[yesterday]
    assert merged[TODAY] == slots(("08:00", "11:00"), ("19:00", "20:00"))
    assert merged[TOMORROW] == incoming[TOMORROW]


def test_merge_keeps_days_missing_from_new_data() -> None:
    """DTEK lists only published days; a missing day is not a cancellation."""
    stored = {TODAY: slots(("08:00", "10:00")), TOMORROW: slots(("01:00", "02:00"))}
    merged = merge_days(stored, {TODAY: ALL_ON}, TODAY, 0)
    assert merged == {TODAY: ALL_ON, TOMORROW: stored[TOMORROW]}


def test_future_changes() -> None:
    """Only changes from the current slot on count; new days are published."""
    old = {TODAY: slots(("08:00", "09:00"), ("18:00", "19:00"))}
    same_future = {TODAY: slots(("07:00", "09:00"), ("18:00", "19:00"))}
    assert future_changes(old, same_future, TODAY, 20) == []

    new = {
        TODAY: slots(("08:00", "09:00"), ("18:00", "20:00")),
        TOMORROW: slots(("01:00", "02:00")),
    }
    changes = future_changes(old, new, TODAY, 20)
    assert [(c.day, c.published) for c in changes] == [
        (TODAY, False),
        (TOMORROW, True),
    ]
    assert changes[0].previous == old[TODAY]


def test_possible_days() -> None:
    """The weekly schedule fills days without an actual schedule."""
    preset = {
        TODAY.isoweekday(): slots(("10:00", "11:00")),
        TOMORROW.isoweekday(): slots(possible=(("12:00", "13:00"),)),
    }
    days = possible_days(preset, TODAY, 3, {TODAY})
    assert list(days) == [TOMORROW]
    assert days[TOMORROW] == slots(possible=(("12:00", "13:00"),))
    # Outages of the weekly schedule are only possible outages.
    days = possible_days(preset, TODAY, 1, set())
    assert days[TODAY] == slots(possible=(("10:00", "11:00"),))


def test_combine_slots() -> None:
    """An outage wins over a possible outage, which wins over power."""
    assert combine_slots(["1100?1", "10?1?1", "111111"]) == "1000?1"
    assert combine_slots([slots(("08:00", "09:00"))]) == slots(("08:00", "09:00"))


def test_combine_days() -> None:
    """A day missing from one schedule counts as power on there."""
    first = {TODAY: slots(("08:00", "10:00")), TOMORROW: slots(("00:00", "01:00"))}
    second = {TODAY: slots(("09:00", "12:00"), possible=(("20:00", "21:00"),))}
    assert combine_days([first, second]) == {
        TODAY: slots(("08:00", "12:00"), possible=(("20:00", "21:00"),)),
        TOMORROW: slots(("00:00", "01:00")),
    }
    assert combine_days([{1: slots()}, {1: slots(("01:00", "02:00")), 2: ALL_ON}]) == {
        1: slots(("01:00", "02:00")),
        2: ALL_ON,
    }
    assert combine_days([]) == {}


def test_combine_slots_every() -> None:
    """With ``every``, an outage of only some schedules is a possible outage."""
    assert combine_slots(["0011?1", "0101?1"], every=True) == "0??1?1"
    assert combine_slots(["0011?1"], every=True) == "0011?1"
    # A day only one group has: nothing says the other one is off too.
    assert combine_days([{TODAY: slots(("08:00", "09:00"))}, {}], every=True) == {
        TODAY: slots(possible=(("08:00", "09:00"),))
    }
