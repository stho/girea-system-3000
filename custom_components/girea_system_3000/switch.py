"""Switch of the room thermostat: week schedule on or off."""
from __future__ import annotations

from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN, get_device_id, thermostat_device_info
from .gira_ble import GiraBLEClient
from .schedule_manager import ScheduleManager


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the schedule switch."""
    data = hass.data[DOMAIN][config_entry.entry_id]
    async_add_entities([GireaScheduleSwitch(data["schedule"], data["client"])])


class GireaScheduleSwitch(SwitchEntity):
    """Switches all switch points of the time program on or off (default: on).

    Writes the time program to the device, with bit 7 of every switch point set
    or cleared. A draft of the days is not written by this switch.
    """

    _attr_has_entity_name = True
    _attr_should_poll = False
    _attr_entity_category = EntityCategory.CONFIG
    _attr_translation_key = "schedule_active"
    _attr_icon = "mdi:calendar-check"

    def __init__(self, manager: ScheduleManager, client: GiraBLEClient) -> None:
        self._manager = manager
        self._attr_unique_id = f"{get_device_id(client.address)}_schedule_active"
        self._attr_device_info = thermostat_device_info(client.address, client.name)

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(self._manager.async_add_listener(self.async_write_ha_state))

    @property
    def is_on(self) -> bool:
        return self._manager.active

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self._manager.async_set_active(True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self._manager.async_set_active(False)
