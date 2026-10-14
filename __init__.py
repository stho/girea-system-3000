"""The Girea System 3000 (Gira Reverse Engineered) integration."""
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er

from .const import DOMAIN, LOGGER, get_device_id
from .gira_ble import GiraBLEClient, GiraPassiveBluetoothDataUpdateCoordinator

PLATFORMS = ["cover"]


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


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Girea System 3000 from a config entry."""
    address = entry.data["address"]
    name = entry.data.get("name", f"Gira Shutter {address[-5:].replace(':', '')}")

    # Must run before the platforms are set up, so the entity finds its old
    # registry entry instead of creating a second one.
    _async_migrate_registry_ids(hass, entry, address)

    # Create the coordinator that will listen for broadcasts
    coordinator = GiraPassiveBluetoothDataUpdateCoordinator(
        hass,
        address=address,
        name=name,
    )

    # Create the client that will send commands
    client = GiraBLEClient(hass, address, name)

    # Store both client and coordinator
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = {
        "coordinator": coordinator,
        "client": client,
    }

    # Forward the setup to the 'cover' platform.
    # The coordinator will automatically start listening when the entity subscribes to it.
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    # Only start the coordinator after all platforms have had a chance to subscribe.
    entry.async_on_unload(coordinator.async_start())
    # Note: async_start() returns an unsubscribe callback, which async_on_unload()
    # calls when the entry is unloaded.

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    # The coordinator handles its own cleanup of the bluetooth callback.
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)

    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id)
    
    return unload_ok
