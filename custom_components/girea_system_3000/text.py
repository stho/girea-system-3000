"""Text entities to edit the week schedule of the room thermostat, one per day."""
from __future__ import annotations

from homeassistant.components.text import TextEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN, get_device_id, thermostat_device_info
from .gira_ble import GiraBLEClient
from .schedule import DAYS, MAX_ENTRIES
from .schedule_manager import ScheduleManager


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up one text entity per weekday."""
    data = hass.data[DOMAIN][config_entry.entry_id]
    async_add_entities(
        GireaScheduleDayText(data["schedule"], data["client"], day) for day in DAYS
    )


class GireaScheduleDayText(TextEntity):
    """Schedule of one weekday, e.g. "5,06:00,21,18:00,5"."""

    _attr_has_entity_name = True
    _attr_should_poll = False
    _attr_entity_category = EntityCategory.CONFIG
    _attr_icon = "mdi:calendar-clock"
    _attr_native_max = 255

    def __init__(self, manager: ScheduleManager, client: GiraBLEClient, day: str) -> None:
        self._manager = manager
        self._day = day
        number = DAYS.index(day) + 1
        # "1 Montag" ... "7 Sonntag", sorted by weekday like in cul_max
        self._attr_translation_key = f"schedule_{number}_{day}"
        self._attr_unique_id = f"{get_device_id(client.address)}_schedule_{day}"
        self._attr_device_info = thermostat_device_info(client.address, client.name)

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(self._manager.async_add_listener(self.async_write_ha_state))

    @property
    def native_value(self) -> str | None:
        return self._manager.day_value(self._day)

    async def async_set_value(self, value: str) -> None:
        """Change the day in the draft; "Wochenplan übertragen" writes it."""
        self._manager.async_set_day(self._day, value)

    @property
    def extra_state_attributes(self) -> dict[str, object]:
        return {
            "draft_pending": self._manager.has_draft,
            "device_value": self._manager.device_value(self._day),
            "switch_points_used": self._manager.entry_count(),
            "switch_points_max": MAX_ENTRIES,
            "format_example": "5,06:00,21,18:00,5",
            "format_hint": "Temperatur,HH:MM,Temperatur,HH:MM,... "
            "erster Wert ab 00:00, letzter Wert bis 24:00",
        }
