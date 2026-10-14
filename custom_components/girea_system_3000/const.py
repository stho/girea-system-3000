"""Constants for the Girea System 3000 integration."""
import logging

from homeassistant.helpers.device_registry import format_mac

DOMAIN = "girea_system_3000"

MANUFACTURER = "Gira"
MODEL = "Jal+Schaltuhr"

# This LOGGER object is now defined in a central place
# and can be imported and used throughout the integration.
LOGGER = logging.getLogger(__package__)


def get_device_id(address: str) -> str:
    """Return the stable device ID (lowercase, colon-separated MAC) for an address.

    Used for the entity unique_id and the device registry identifier, so both
    stay independent of the config entry ID and of how the user typed the MAC.
    """
    return format_mac(address)
