"""State of the week schedule of one thermostat, shared by its entities.

Like in the MAX! integration "cul_max" the days are edited as a draft: changing
a day does not talk to the device. "Übertragen" writes the whole week at once,
"Verwerfen" drops the draft. The last schedule written to or read from the
device is stored, so the entities show it after a restart without connecting.
"""
from __future__ import annotations

from collections.abc import Callable

from homeassistant.core import CALLBACK_TYPE, HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util

from .const import DOMAIN, LOGGER
from .gira_ble import GiraBLEClient, decode_dpt9, encode_dpt9
from .schedule import (
    DAYS,
    DaySchedule,
    Entry,
    ScheduleError,
    decode_entry,
    encode_entry,
    entries_to_week,
    format_day,
    parse_day,
    week_to_entries,
)

STORAGE_VERSION = 1


def _validation_error(err: ScheduleError) -> ServiceValidationError:
    """Translated error for an invalid schedule (texts under "exceptions")."""
    return ServiceValidationError(
        translation_domain=DOMAIN,
        translation_key=err.key,
        translation_placeholders=err.placeholders,
    )


def _parse_week(texts: list[str]) -> list[DaySchedule]:
    """Parse the seven day texts. Values read from the device may be out of the
    allowed range (set with the Gira app), hence the translated error."""
    try:
        return [parse_day(text) for text in texts]
    except ScheduleError as err:
        raise _validation_error(err) from err


def week_from_device(raw_entries: list[bytes]) -> tuple[list[DaySchedule] | None, bool]:
    """Decode the entries read from the device into a week and the active flag.

    If some entries are active, only those count: the standard mode of the
    Gira app keeps switched off blocks in the list. If none is active the
    schedule was switched off as a whole and all entries are shown.
    """
    entries = [
        entry
        for entry in (decode_entry(raw, decode_dpt9) for raw in raw_entries)
        if entry is not None
    ]
    active = [entry for entry in entries if entry.active]
    return entries_to_week(active or entries), bool(active)


class ScheduleManager:
    """Week schedule of one thermostat: stored state, draft and transfer."""

    def __init__(self, hass: HomeAssistant, client: GiraBLEClient, device_id: str) -> None:
        self.hass = hass
        self._client = client
        self._store: Store[dict] = Store(
            hass, STORAGE_VERSION, f"{DOMAIN}.schedule.{device_id.replace(':', '')}"
        )
        # Days as text, Monday first; None while the schedule is unknown
        self._week: list[str] | None = None
        self._active = True
        self._extended_mode: bool | None = None
        self._draft: dict[str, str] = {}
        self._listeners: list[Callable[[], None]] = []

    # --- State for the entities ---------------------------------------------

    @property
    def active(self) -> bool:
        """Whether the switch points are active in the device."""
        return self._active

    @property
    def known(self) -> bool:
        """Whether the schedule of the device is known."""
        return self._week is not None

    @property
    def extended_mode(self) -> bool | None:
        """Whether the device was in the extended mode when last read."""
        return self._extended_mode

    @property
    def has_draft(self) -> bool:
        """Whether there are changes that were not written to the device yet."""
        return bool(self._draft)

    def day_value(self, day: str) -> str | None:
        """Text of a day, the draft if there is one."""
        if day in self._draft:
            return self._draft[day]
        if self._week is None:
            return None
        return self._week[DAYS.index(day)]

    def device_value(self, day: str) -> str | None:
        """Text of a day as it is in the device."""
        return None if self._week is None else self._week[DAYS.index(day)]

    def entry_count(self) -> int | None:
        """Number of switch points the current week (with draft) needs."""
        try:
            return len(week_to_entries(self._draft_week()))
        except (ScheduleError, HomeAssistantError):
            return None

    @callback
    def async_add_listener(self, listener: Callable[[], None]) -> CALLBACK_TYPE:
        """Call the listener when anything changes; returns the remove function."""
        self._listeners.append(listener)
        return lambda: self._listeners.remove(listener)

    @callback
    def _notify(self) -> None:
        for listener in list(self._listeners):
            listener()

    # --- Loading and storing ------------------------------------------------

    async def async_load(self) -> None:
        """Load the schedule stored by an earlier run."""
        data = await self._store.async_load()
        if not data:
            return
        week = data.get("week")
        if isinstance(week, list) and len(week) == len(DAYS):
            self._week = [str(day) for day in week]
        self._active = bool(data.get("active", True))
        self._extended_mode = data.get("extended_mode")

    async def _async_save(self) -> None:
        await self._store.async_save(
            {"week": self._week, "active": self._active, "extended_mode": self._extended_mode}
        )

    # --- Editing --------------------------------------------------------------

    @callback
    def async_set_day(self, day: str, value: str) -> None:
        """Change one day in the draft. Raises ServiceValidationError if invalid."""
        try:
            text = format_day(parse_day(value))
        except ScheduleError as err:
            raise _validation_error(err) from err
        if self._week is not None and text == self._week[DAYS.index(day)]:
            self._draft.pop(day, None)
        else:
            self._draft[day] = text
        self._notify()

    @callback
    def async_discard_draft(self) -> None:
        """Drop all changes that were not written to the device."""
        self._draft.clear()
        self._notify()

    def _draft_week(self) -> list[DaySchedule]:
        """The week to write: the stored days with the draft applied."""
        texts = []
        for day in DAYS:
            text = self.day_value(day)
            if text is None:
                raise HomeAssistantError(
                    translation_domain=DOMAIN, translation_key="schedule_incomplete"
                )
            texts.append(text)
        return _parse_week(texts)

    # --- Talking to the device ------------------------------------------------

    async def async_apply(self) -> None:
        """Write the week (with the draft) to the device."""
        await self._async_write(self._draft_week(), self._active)
        self._draft.clear()
        self._notify()

    async def async_set_active(self, active: bool) -> None:
        """Switch all switch points on or off. The draft is kept as it is."""
        if self._week is None:
            # Nothing in the device that could be switched; remember the choice
            self._active = active
            await self._async_save()
            self._notify()
            return
        await self._async_write(_parse_week(self._week), active)
        self._notify()

    async def _async_write(self, week: list[DaySchedule], active: bool) -> None:
        try:
            entries: list[Entry] = week_to_entries(week, active)
        except ScheduleError as err:
            raise _validation_error(err) from err
        LOGGER.debug("Writing %d switch points to %s", len(entries), self._client.name)
        await self._client.async_write_schedule(
            [encode_entry(entry, encode_dpt9) for entry in entries], dt_util.now()
        )
        self._week = [format_day(day) for day in week]
        self._active = active
        self._extended_mode = True
        await self._async_save()

    async def async_read(self) -> None:
        """Read the schedule from the device. Drops the draft."""
        extended, raw_entries = await self._client.async_read_schedule()
        week, active = week_from_device(raw_entries)
        LOGGER.debug(
            "Read %d switch points from %s (extended mode: %s)",
            len(raw_entries),
            self._client.name,
            extended,
        )
        self._week = None if week is None else [format_day(day) for day in week]
        self._active = active if week is not None else self._active
        self._extended_mode = extended
        self._draft.clear()
        await self._async_save()
        self._notify()
