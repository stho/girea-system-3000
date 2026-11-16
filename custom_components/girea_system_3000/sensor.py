"""Platform for the Girea System 3000 room thermostat (temperature sensors)."""
from __future__ import annotations

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import UnitOfTemperature
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import CONNECTION_BLUETOOTH, DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, LOGGER, MANUFACTURER, MODEL_THERMOSTAT, get_device_id
from .gira_ble import GiraBLEClient, GiraPassiveBluetoothDataUpdateCoordinator

SENSORS: tuple[SensorEntityDescription, ...] = (
    SensorEntityDescription(
        key="temperature",
        translation_key="temperature",
        device_class=SensorDeviceClass.TEMPERATURE,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    SensorEntityDescription(
        key="setpoint",
        translation_key="setpoint",
        device_class=SensorDeviceClass.TEMPERATURE,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        state_class=SensorStateClass.MEASUREMENT,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the thermostat sensors from a config entry."""
    data = hass.data[DOMAIN][config_entry.entry_id]
    coordinator: GiraPassiveBluetoothDataUpdateCoordinator = data["coordinator"]
    client: GiraBLEClient = data["client"]

    async_add_entities(
        GireaThermostatSensor(coordinator, client, description) for description in SENSORS
    )
    LOGGER.debug("Thermostat sensors set up for %s", config_entry.title)


class GireaThermostatSensor(
    CoordinatorEntity[GiraPassiveBluetoothDataUpdateCoordinator], SensorEntity
):
    """Temperature value broadcast by a Gira room thermostat."""

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: GiraPassiveBluetoothDataUpdateCoordinator,
        client: GiraBLEClient,
        description: SensorEntityDescription,
    ) -> None:
        super().__init__(coordinator)
        self.entity_description = description
        device_id = get_device_id(client.address)
        self._attr_unique_id = f"{device_id}_{description.key}"
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
    def native_value(self) -> float | None:
        """Last temperature received in a broadcast."""
        data = self.coordinator.data
        if not data:
            return None
        return data.get(self.entity_description.key)
