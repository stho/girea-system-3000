"""Buttons of the room thermostat to transfer, discard or read the week schedule."""
from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from homeassistant.components.button import ButtonEntity, ButtonEntityDescription
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN, get_device_id, thermostat_device_info
from .gira_ble import GiraBLEClient
from .schedule_manager import ScheduleManager


async def _async_discard(manager: ScheduleManager) -> None:
    manager.async_discard_draft()


@dataclass(frozen=True, kw_only=True)
class GireaButtonDescription(ButtonEntityDescription):
    """Button with the action it runs on the schedule."""

    press: Callable[[ScheduleManager], Awaitable[None]]


BUTTONS: tuple[GireaButtonDescription, ...] = (
    GireaButtonDescription(
        key="schedule_apply",
        translation_key="schedule_apply",
        icon="mdi:upload",
        press=lambda manager: manager.async_apply(),
    ),
    GireaButtonDescription(
        key="schedule_discard",
        translation_key="schedule_discard",
        icon="mdi:undo",
        press=_async_discard,
    ),
    GireaButtonDescription(
        key="schedule_read",
        translation_key="schedule_read",
        icon="mdi:download",
        press=lambda manager: manager.async_read(),
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the schedule buttons."""
    data = hass.data[DOMAIN][config_entry.entry_id]
    async_add_entities(
        GireaScheduleButton(data["schedule"], data["client"], description)
        for description in BUTTONS
    )


class GireaScheduleButton(ButtonEntity):
    """Runs one action on the week schedule."""

    entity_description: GireaButtonDescription
    _attr_has_entity_name = True
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(
        self,
        manager: ScheduleManager,
        client: GiraBLEClient,
        description: GireaButtonDescription,
    ) -> None:
        self._manager = manager
        self.entity_description = description
        self._attr_unique_id = f"{get_device_id(client.address)}_{description.key}"
        self._attr_device_info = thermostat_device_info(client.address, client.name)

    async def async_press(self) -> None:
        await self.entity_description.press(self._manager)
