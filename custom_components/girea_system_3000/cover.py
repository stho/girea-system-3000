"""Platform for the Girea System 3000 cover integration."""
from __future__ import annotations

from typing import Any

from homeassistant.components.cover import (
    CoverEntity,
    CoverEntityFeature,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import CONNECTION_BLUETOOTH, DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, LOGGER, MANUFACTURER, MODEL, get_device_id
from .gira_ble import GiraBLEClient, GiraPassiveBluetoothDataUpdateCoordinator


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Girea System 3000 cover from a config entry."""
    data = hass.data[DOMAIN][config_entry.entry_id]
    coordinator: GiraPassiveBluetoothDataUpdateCoordinator = data["coordinator"]
    client: GiraBLEClient = data["client"]

    # Add the Gira shutter as a Home Assistant Cover entity
    cover_entity = GireaSystem3000Cover(coordinator, client)
    async_add_entities([cover_entity])
    
    LOGGER.debug("Coordinator setup complete for %s", config_entry.title)


class GireaSystem3000Cover(
    CoordinatorEntity[GiraPassiveBluetoothDataUpdateCoordinator], CoverEntity
):
    """Representation of a Gira System 3000 Cover."""

    _attr_has_entity_name = True
    _attr_name = None
    _attr_supported_features = (
        CoverEntityFeature.OPEN
        | CoverEntityFeature.CLOSE
        | CoverEntityFeature.STOP
        | CoverEntityFeature.SET_POSITION
    )
    # The position only arrives with a delay, after the shutter was moved. Until
    # then Home Assistant still shows the old end position, and the frontend
    # disables the button for the opposite direction (e.g. "close" while the
    # position still says 0 %), although the shutter is already moving. An assumed
    # state keeps both buttons usable at any time.
    _attr_assumed_state = True

    def __init__(
        self,
        coordinator: GiraPassiveBluetoothDataUpdateCoordinator,
        client: GiraBLEClient,
    ) -> None:
        """Initialize the cover."""
        super().__init__(coordinator)
        self._client = client
        device_id = get_device_id(client.address)
        self._attr_unique_id = device_id
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, device_id)},
            connections={(CONNECTION_BLUETOOTH, client.address.upper())},
            name=client.name,
            manufacturer=MANUFACTURER,
            model=MODEL,
        )
        self._attr_current_cover_position = None  # Initialize the state to None
        LOGGER.debug("Created cover entity for %s", client.name)

    @property
    def available(self) -> bool:
        """Return if the entity is available."""
        # Availability is deliberately not derived from received broadcasts.
        # If the device cannot be reached, the commands raise an error that is
        # shown to the user.
        return True

    async def async_open_cover(self, **kwargs: Any) -> None:
        """Open the cover."""
        await self._client.send_up_command()

    async def async_close_cover(self, **kwargs: Any) -> None:
        """Close the cover."""
        await self._client.send_down_command()

    async def async_stop_cover(self, **kwargs: Any) -> None:
        """Stop the cover."""
        await self._client.send_stop_command()

    async def async_set_cover_position(self, **kwargs: Any) -> None:
        """Set cover position."""
        await self._client.set_absolute_position(kwargs['position'])

    @property
    def current_cover_position(self) -> int | None:
        """Return the current position of the cover."""
        # Return the cached state attribute
        return self._attr_current_cover_position

    @property
    def is_closed(self) -> bool | None:
        """Return if the cover is closed or not."""
        position = self.current_cover_position
        if position is None:
            return None
        return position == 0

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        if self.coordinator.data is not None:
            new_position = self.coordinator.data.get("position")
            # Only update the state if a new position is available
            if new_position is not None:
                self._attr_current_cover_position = new_position
                LOGGER.debug(
                    "Cover entity received update. New position: %s",
                    self.current_cover_position,
                )
        self.async_write_ha_state()
