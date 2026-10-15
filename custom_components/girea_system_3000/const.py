"""Constants for the Girea System 3000 integration."""
from __future__ import annotations

import logging
import re

from homeassistant.helpers.device_registry import format_mac

DOMAIN = "girea_system_3000"

MANUFACTURER = "Gira"
MODEL = "Jal+Schaltuhr"

# This LOGGER object is now defined in a central place
# and can be imported and used throughout the integration.
LOGGER = logging.getLogger(__package__)


def normalize_address(address: str) -> str | None:
    """Return the MAC as upper case, colon separated (as Home Assistant's Bluetooth
    stack reports it), or None if it is not a valid MAC address.

    Accepts the common ways to write it: AA:BB:..., aa-bb-..., AABB....
    """
    cleaned = address.strip().upper().replace(":", "").replace("-", "")
    if not re.fullmatch(r"[0-9A-F]{12}", cleaned):
        return None
    return ":".join(cleaned[i : i + 2] for i in range(0, 12, 2))


def get_device_id(address: str) -> str:
    """Return the stable device ID (lowercase, colon-separated MAC) for an address.

    Used for the entity unique_id and the device registry identifier, so both
    stay independent of the config entry ID and of how the user typed the MAC.
    """
    return format_mac(address)
