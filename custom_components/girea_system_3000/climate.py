"""Platform for the Girea System 3000 room thermostat (target temperature)."""
from __future__ import annotations

from typing import Any

from homeassistant.components.climate import (
    ClimateEntity,
    ClimateEntityFeature,
    HVACMode,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import ATTR_TEMPERATURE, UnitOfTemperature
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import CONNECTION_BLUETOOTH, DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, LOGGER, MANUFACTURER, MODEL_THERMOSTAT, get_device_id
from .gira_ble import (
    SETPOINT_MAX,
    SETPOINT_MIN,
    SETPOINT_STEP,
    GiraBLEClient,
    GiraPassiveBluetoothDataUpdateCoordinator,
)


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the thermostat climate entity from a config entry."""
    data = hass.data[DOMAIN][config_entry.entry_id]
    async_add_entities([GireaThermostat(data["coordinator"], data["client"])])
    LOGGER.debug("Thermostat climate entity set up for %s", config_entry.title)


class GireaThermostat(
    CoordinatorEntity[GiraPassiveBluetoothDataUpdateCoordinator], ClimateEntity
):
    """Gira room thermostat: shows the temperatures and sets the target temperature."""

    _attr_has_entity_name = True
    _attr_name = None  # the entity is the main feature of the device
    _attr_temperature_unit = UnitOfTemperature.CELSIUS
    _attr_supported_features = ClimateEntityFeature.TARGET_TEMPERATURE
    # The thermostat has no switch for the operating mode that is known
    _attr_hvac_modes = [HVACMode.HEAT]
    _attr_hvac_mode = HVACMode.HEAT
    _attr_min_temp = SETPOINT_MIN
    _attr_max_temp = SETPOINT_MAX
    _attr_target_temperature_step = SETPOINT_STEP
    _enable_turn_on_off_backwards_compatibility = False

    def __init__(
        self,
        coordinator: GiraPassiveBluetoothDataUpdateCoordinator,
        client: GiraBLEClient,
    ) -> None:
        super().__init__(coordinator)
        self._client = client
        device_id = get_device_id(client.address)
        self._attr_unique_id = f"{device_id}_climate"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, device_id)},
            connections={(CONNECTION_BLUETOOTH, client.address.upper())},
            name=client.name,
            manufacturer=MANUFACTURER,
            model=MODEL_THERMOSTAT,
        )

    @property
    def available(self) -> bool:
        """The coordinator is passive (no polling); the state stays unknown until
        the first broadcast arrives."""
        return True

    @property
    def current_temperature(self) -> float | None:
        """Last measured temperature received in a broadcast."""
        data = self.coordinator.data
        return data.get("temperature") if data else None

    @property
    def target_temperature(self) -> float | None:
        """Last target temperature received in a broadcast."""
        data = self.coordinator.data
        return data.get("setpoint") if data else None

    async def async_set_temperature(self, **kwargs: Any) -> None:
        """Set the target temperature (raises HomeAssistantError if it fails)."""
        temperature = kwargs.get(ATTR_TEMPERATURE)
        if temperature is None:
            return
        await self._client.set_setpoint(temperature)
        # The thermostat confirms the new value in a broadcast. Show it right away,
        # in the 0.5 degree steps of the device.
        data = dict(self.coordinator.data or {})
        data["setpoint"] = round(temperature * 2) / 2
        self.coordinator.data = data
        self.coordinator.async_update_listeners()

    async def async_set_hvac_mode(self, hvac_mode: HVACMode) -> None:
        """Only heating is supported; nothing to switch."""
