"""Week schedule of the Gira room thermostat ("erweitert" mode of the time program).

Pure logic without Home Assistant, so it can be tested on its own.

Text format per day (the same as the MAX! integration "cul_max"):

    5,06:00,21,18:00,5

means 5 °C from 00:00, 21 °C from 06:00 and 5 °C from 18:00 until the end of
the day. The first value is the temperature at midnight, then follow pairs of a
switch time and the temperature from that time on.

The device stores a list of up to 40 switch points instead (object 0x03F4,
property 0x9C, see GIRA_SYSTEM_3000_BLUETOOTH.md). Every switch point has a
start time, a day mask and a temperature. Between midnight and the first
switch point of a day the last temperature of the previous day stays active.
The conversion therefore only writes a switch point at 00:00 when the first
value of the day differs from the last value of the previous day. Every
switch point is written for exactly one day, never merged across days.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

DAYS = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")

MAX_ENTRIES = 40  # switch points the device accepts in the "erweitert" mode
TEMP_MIN = 5.0  # lowest value tested on the device (frost protection of the mode)
TEMP_MAX = 30.0
TEMP_STEP = 0.5
MINUTES_PER_DAY = 24 * 60

ENTRY_LENGTH = 10
ENTRY_ACTIVE = 0x80  # bit 7 of the day byte, bits 0..6 are Monday..Sunday
# Bytes 4..8 of every entry. Always the same in all logs of the Gira app.
ENTRY_CONSTANT = bytes.fromhex("2001000001")


class ScheduleError(ValueError):
    """Invalid schedule. `key` and `placeholders` select the translated message."""

    def __init__(self, key: str, **placeholders: object) -> None:
        super().__init__(f"{key}: {placeholders}")
        self.key = key
        self.placeholders = {k: str(v) for k, v in placeholders.items()}


@dataclass(frozen=True)
class DaySchedule:
    """Temperature at midnight and the switch points (minute of day, temperature)."""

    start: float
    points: tuple[tuple[int, float], ...] = ()

    @property
    def end(self) -> float:
        """Temperature at the end of the day."""
        return self.points[-1][1] if self.points else self.start


@dataclass(frozen=True)
class Entry:
    """One switch point as stored in the device."""

    minute: int
    days: int  # bit mask, bit 0 = Monday ... bit 6 = Sunday
    temperature: float
    active: bool = True


# --- Text format ---------------------------------------------------------------


def parse_temperature(value: str) -> float:
    """Parse a temperature like "21" or "19.5"."""
    try:
        temperature = float(value.strip())
    except ValueError as err:
        raise ScheduleError("schedule_temperature_invalid", value=value) from err
    if not TEMP_MIN <= temperature <= TEMP_MAX:
        raise ScheduleError(
            "schedule_temperature_range", value=value, min=TEMP_MIN, max=TEMP_MAX
        )
    if (temperature / TEMP_STEP) % 1:
        raise ScheduleError("schedule_temperature_step", value=value, step=TEMP_STEP)
    return temperature


def parse_time(value: str) -> int:
    """Parse H:MM or HH:MM into minutes since midnight (00:01 .. 23:59)."""
    match = re.fullmatch(r"(\d{1,2}):(\d{2})", value.strip())
    if not match:
        raise ScheduleError("schedule_time_invalid", value=value)
    hour, minute = int(match.group(1)), int(match.group(2))
    if hour > 23 or minute > 59:
        raise ScheduleError("schedule_time_invalid", value=value)
    return hour * 60 + minute


def parse_day(text: str) -> DaySchedule:
    """Parse the text of one day, e.g. "5,06:00,21,18:00,5".

    The comma separates the values, so decimals need a dot (19.5).
    """
    tokens = [token.strip() for token in text.split(",")]
    if not text.strip() or any(not token for token in tokens) or len(tokens) % 2 == 0:
        raise ScheduleError("schedule_format", value=text)

    start = parse_temperature(tokens[0])
    points: list[tuple[int, float]] = []
    last_minute = 0
    for index in range(1, len(tokens), 2):
        minute = parse_time(tokens[index])
        if minute <= last_minute:
            raise ScheduleError("schedule_time_order", value=tokens[index])
        points.append((minute, parse_temperature(tokens[index + 1])))
        last_minute = minute
    return DaySchedule(start, tuple(points))


def format_temperature(temperature: float) -> str:
    """Render a temperature compactly: 21 or 19.5 (as cul_max does)."""
    temperature = round(temperature * 2) / 2
    return str(int(temperature)) if temperature.is_integer() else f"{temperature:.1f}"


def format_day(day: DaySchedule) -> str:
    """Render one day in the text format, the inverse of parse_day."""
    parts = [format_temperature(day.start)]
    for minute, temperature in day.points:
        parts.append(f"{minute // 60:02d}:{minute % 60:02d}")
        parts.append(format_temperature(temperature))
    return ",".join(parts)


# --- Conversion between the week and the device entries -------------------------


def week_to_entries(week: list[DaySchedule], active: bool = True) -> list[Entry]:
    """Convert seven days (Monday first) into the switch points of the device.

    A switch point at 00:00 is only added if the day starts with another
    temperature than the previous day ends with. Raises ScheduleError if the
    device cannot hold all switch points.
    """
    if len(week) != len(DAYS):
        raise ValueError("a week has seven days")

    entries: list[Entry] = []
    for index, day in enumerate(week):
        previous = week[index - 1]  # Sunday for Monday
        if day.start != previous.end:
            entries.append(Entry(0, 1 << index, day.start, active))
        entries.extend(
            Entry(minute, 1 << index, temperature, active)
            for minute, temperature in day.points
        )

    if not entries:
        # The same temperature all week: one switch point is still needed, or
        # the device would keep whatever temperature it has.
        entries.append(Entry(0, 1, week[0].start, active))

    if len(entries) > MAX_ENTRIES:
        raise ScheduleError("schedule_too_many", count=len(entries), max=MAX_ENTRIES)
    return entries


def entries_to_week(entries: list[Entry]) -> list[DaySchedule] | None:
    """Convert the switch points of the device into seven days (Monday first).

    Inactive switch points are included, so a switched off schedule can still
    be shown and edited. Entries for several days (as the Gira app creates
    them) are shown at each of their days. Returns None if there are none.
    """
    if not entries:
        return None

    per_day: list[dict[int, float]] = [{} for _ in DAYS]
    for entry in entries:
        for index in range(len(DAYS)):
            if entry.days & (1 << index):
                per_day[index][entry.minute] = entry.temperature

    if not any(per_day):
        return None

    # Temperature at the end of each day, needed for days without a 00:00 point.
    ends: list[float | None] = [
        points[max(points)] if points else None for points in per_day
    ]

    def carried_over(index: int) -> float:
        """Last temperature before the given day (searching back up to a week)."""
        for back in range(1, len(DAYS) + 1):
            end = ends[(index - back) % len(DAYS)]
            if end is not None:
                return end
        raise AssertionError("unreachable: at least one day has points")

    week: list[DaySchedule] = []
    for index, points in enumerate(per_day):
        start = points.pop(0) if 0 in points else carried_over(index)
        week.append(DaySchedule(start, tuple(sorted(points.items()))))
    return week


# --- Bytes of one entry -----------------------------------------------------------


def encode_entry(entry: Entry, encode_temperature) -> bytes:
    """Encode an entry as the 10 bytes of the device.

    `encode_temperature` is the DPT 9 encoder (passed in to keep this module
    free of the Bluetooth code).
    """
    day_byte = (entry.days & 0x7F) | (ENTRY_ACTIVE if entry.active else 0)
    return (
        bytes((entry.minute // 60, entry.minute % 60, day_byte))
        + ENTRY_CONSTANT
        + encode_temperature(entry.temperature)
    )


def decode_entry(raw: bytes, decode_temperature) -> Entry | None:
    """Decode the 10 bytes of an entry. Returns None if they make no sense."""
    if len(raw) != ENTRY_LENGTH:
        return None
    hour, minute, day_byte = raw[0], raw[1], raw[2]
    temperature = decode_temperature(raw[8:10])
    if hour > 23 or minute > 59 or temperature is None:
        return None
    return Entry(hour * 60 + minute, day_byte & 0x7F, temperature, bool(day_byte & ENTRY_ACTIVE))
