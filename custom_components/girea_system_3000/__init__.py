"""The System 3000 integration."""
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er

from .const import (
    CONF_DEVICE_TYPE,
    DEVICE_TYPE_COVER,
    DEVICE_TYPE_THERMOSTAT,
    DOMAIN,
    LOGGER,
    get_device_id,
)
from .frontend import async_register_frontend
from .gira_ble import GiraBLEClient, GiraPassiveBluetoothDataUpdateCoordinator
from .schedule_manager import ScheduleManager

PLATFORMS_BY_DEVICE_TYPE = {
    DEVICE_TYPE_COVER: ["cover"],
    DEVICE_TYPE_THERMOSTAT: ["climate", "sensor", "text", "switch", "button"],
}


def _platforms(entry: ConfigEntry) -> list[str]:
    """Platforms of the entry. Entries without a device type are shutters."""
    return PLATFORMS_BY_DEVICE_TYPE[entry.data.get(CONF_DEVICE_TYPE, DEVICE_TYPE_COVER)]


def _async_get_entry_device(
    dev_reg: dr.DeviceRegistry, entry: ConfigEntry, identifier: tuple[str, str]
) -> dr.DeviceEntry | None:
    """Return this config entry's device with the given identifier, if any.

    Device identifiers are no longer unique across config entries, so the
    lookup has to be scoped to the config entry. Older Home Assistant versions
    do not have the scoped lookup yet and fall back to the old method.
    """
    if hasattr(dev_reg, "async_get_device_by_identifier"):
        return dev_reg.async_get_device_by_identifier(identifier, entry.entry_id)
    return dev_reg.async_get_device(identifiers={identifier})


@callback
def _async_migrate_registry_ids(
    hass: HomeAssistant, entry: ConfigEntry, address: str
) -> None:
    """Migrate IDs from the old entry_id based scheme to the MAC based one.

    Before, the cover's unique_id and the device identifier were the config
    entry ID, and the device carried a bogus connection. Without this migration
    existing installations would get a new entity and a new device, losing
    history, entity_id customizations and area assignments.
    """
    device_id = get_device_id(address)

    ent_reg = er.async_get(hass)
    old_entity_id = ent_reg.async_get_entity_id("cover", DOMAIN, entry.entry_id)
    if old_entity_id and not ent_reg.async_get_entity_id("cover", DOMAIN, device_id):
        LOGGER.debug("Migrating unique_id of %s to %s", old_entity_id, device_id)
        ent_reg.async_update_entity(old_entity_id, new_unique_id=device_id)

    dev_reg = dr.async_get(hass)
    old_device = _async_get_entry_device(dev_reg, entry, (DOMAIN, entry.entry_id))
    if old_device and not _async_get_entry_device(dev_reg, entry, (DOMAIN, device_id)):
        LOGGER.debug("Migrating device identifiers of %s to %s", old_device.id, device_id)
        dev_reg.async_update_device(
            old_device.id,
            new_identifiers={(DOMAIN, device_id)},
            new_connections={(dr.CONNECTION_BLUETOOTH, address.upper())},
        )


async def _async_initial_schedule_read(schedule: ScheduleManager, name: str) -> None:
    """Read the week schedule once; a failure only means it stays unknown."""
    try:
        await schedule.async_read()
    except HomeAssistantError as err:
        LOGGER.warning(
            "Could not read the week schedule of %s: %s. Use the button "
            "'Wochenplan vom Gerät lesen' to try again.",
            name,
            err,
        )


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Girea System 3000 from a config entry."""
    await async_register_frontend(hass)
    address = entry.data["address"]
    device_type = entry.data.get(CONF_DEVICE_TYPE, DEVICE_TYPE_COVER)
    kind = "Thermostat" if device_type == DEVICE_TYPE_THERMOSTAT else "Shutter"
    name = entry.data.get("name", f"Gira {kind} {address[-5:].replace(':', '')}")

    # Must run before the platforms are set up, so the entity finds its old
    # registry entry instead of creating a second one. Only shutters have
    # entries from before the MAC based IDs.
    if device_type == DEVICE_TYPE_COVER:
        _async_migrate_registry_ids(hass, entry, address)

    # Create the coordinator that will listen for broadcasts
    coordinator = GiraPassiveBluetoothDataUpdateCoordinator(
        hass,
        address=address,
        name=name,
    )

    # Create the client that will send commands
    client = GiraBLEClient(
        hass, address, name, thermostat=device_type == DEVICE_TYPE_THERMOSTAT
    )

    # Store both client and coordinator
    data = hass.data.setdefault(DOMAIN, {})[entry.entry_id] = {
        "coordinator": coordinator,
        "client": client,
    }

    if device_type == DEVICE_TYPE_THERMOSTAT:
        # Week schedule: shown from the store, read from the device only once
        # when nothing is stored yet (reading connects to the device).
        schedule = ScheduleManager(hass, client, get_device_id(address))
        await schedule.async_load()
        data["schedule"] = schedule
        if not schedule.known:
            entry.async_create_background_task(
                hass, _async_initial_schedule_read(schedule, name), "girea_schedule_read"
            )

    # Forward the setup to the platforms of the device type ('cover' or 'sensor').
    # The coordinator will automatically start listening when the entity subscribes to it.
    await hass.config_entries.async_forward_entry_setups(entry, _platforms(entry))

    # Only start the coordinator after all platforms have had a chance to subscribe.
    entry.async_on_unload(coordinator.async_start())
    # Note: async_start() returns an unsubscribe callback, which async_on_unload()
    # calls when the entry is unloaded.

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    # The coordinator handles its own cleanup of the bluetooth callback.
    unload_ok = await hass.config_entries.async_unload_platforms(entry, _platforms(entry))

    if unload_ok:
        data = hass.data[DOMAIN].pop(entry.entry_id)
        # Close a connection that is kept open for reuse
        await data["client"].async_shutdown()
    
    return unload_ok
