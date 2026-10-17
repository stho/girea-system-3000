"""Platform for the Girea System 3000 cover integration."""
from __future__ import annotations

import time
from typing import Any

from homeassistant.components.cover import (
    CoverEntity,
    CoverEntityFeature,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import CALLBACK_TYPE, HomeAssistant, callback
from homeassistant.helpers.device_registry import CONNECTION_BLUETOOTH, DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.event import async_call_later
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, LOGGER, MANUFACTURER, MODEL, get_device_id
from .gira_ble import GiraBLEClient, GiraPassiveBluetoothDataUpdateCoordinator

# A full run of the shutter takes about 65 s. If no "stopped" status arrives, the
# opening/closing state is reset after this time so it can never get stuck.
MOVEMENT_TIMEOUT = 75  # seconds
# Right after a command the device may still report its old "stopped" status
# (the status only arrives with a delay). "Stopped" broadcasts are ignored for
# this long, so they do not cancel the movement that was just started.
MOVEMENT_STATUS_GRACE = 20  # seconds


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
        self._attr_is_opening = False
        self._attr_is_closing = False
        self._movement_started: float | None = None
        self._movement_timeout: CALLBACK_TYPE | None = None
        self._last_movement_update: float | None = None
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
        self._start_movement(opening=True)

    async def async_close_cover(self, **kwargs: Any) -> None:
        """Close the cover."""
        await self._client.send_down_command()
        self._start_movement(opening=False)

    async def async_stop_cover(self, **kwargs: Any) -> None:
        """Stop the cover."""
        await self._client.send_stop_command()
        self._stop_movement()

    async def async_set_cover_position(self, **kwargs: Any) -> None:
        """Set cover position."""
        target = kwargs["position"]
        current = self.current_cover_position
        await self._client.set_absolute_position(target)
        if current is None or target == current:
            # Direction unknown (or nothing to do): do not guess
            self._stop_movement()
        else:
            self._start_movement(opening=target > current)

    @callback
    def _start_movement(self, *, opening: bool) -> None:
        """Show opening/closing right after a command, without waiting for the device.

        The direction comes from the command that was sent. The device's own
        status broadcast only arrives after a delay and ends the movement again.
        """
        self._cancel_movement_timeout()
        self._attr_is_opening = opening
        self._attr_is_closing = not opening
        self._movement_started = time.monotonic()
        self._movement_timeout = async_call_later(
            self.hass, MOVEMENT_TIMEOUT, self._async_movement_timeout
        )
        self.async_write_ha_state()

    @callback
    def _stop_movement(self) -> None:
        """Reset the opening/closing state."""
        self._cancel_movement_timeout()
        self._movement_started = None
        if self._attr_is_opening or self._attr_is_closing:
            self._attr_is_opening = False
            self._attr_is_closing = False
        self.async_write_ha_state()

    @callback
    def _async_movement_timeout(self, _now: object) -> None:
        """Safety net: no "stopped" status arrived in time."""
        self._movement_timeout = None
        self._stop_movement()

    def _cancel_movement_timeout(self) -> None:
        if self._movement_timeout is not None:
            self._movement_timeout()
            self._movement_timeout = None

    async def async_will_remove_from_hass(self) -> None:
        """Cancel the pending timer."""
        self._cancel_movement_timeout()
        await super().async_will_remove_from_hass()

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

            # A new "stopped" status ends the opening/closing state, unless it is
            # old (repeated) or arrived right after a command (see grace period).
            updated = self.coordinator.data.get("moving_updated")
            if updated is not None and updated != self._last_movement_update:
                self._last_movement_update = updated
                if (
                    not self.coordinator.data.get("moving")
                    and self._movement_started is not None
                    and updated - self._movement_started > MOVEMENT_STATUS_GRACE
                ):
                    self._stop_movement()
        self.async_write_ha_state()
