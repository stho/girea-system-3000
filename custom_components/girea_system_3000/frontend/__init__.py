"""Frontend card of the Girea System 3000 integration (week schedule card)."""
from __future__ import annotations

import logging
from pathlib import Path

from homeassistant.core import HomeAssistant

_LOGGER = logging.getLogger(__package__)

URL_BASE = "/girea_system_3000"
CARD_FILE = "gira-week-profile-card.js"
# Raise the version with every change of the card: the browser caches the file.
CARD_VERSION = "1.0.0"
_REGISTERED = "girea_system_3000_frontend_registered"


async def async_register_frontend(hass: HomeAssistant) -> None:
    """Serve the card and load it on every dashboard (once per start)."""
    if hass.data.get(_REGISTERED):
        return
    hass.data[_REGISTERED] = True
    try:
        from homeassistant.components.frontend import add_extra_js_url
        from homeassistant.components.http import StaticPathConfig
        url = f"{URL_BASE}/{CARD_FILE}"
        await hass.http.async_register_static_paths(
            [StaticPathConfig(url, str(Path(__file__).parent / CARD_FILE), True)]
        )
        add_extra_js_url(hass, f"{url}?v={CARD_VERSION}")
    except Exception as err:  # noqa: BLE001 - the card is optional
        _LOGGER.warning("Could not register the week schedule card: %s", err)
