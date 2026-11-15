"""Config flow for Girea System 3000 (Gira Reverse Engineered) integration."""
from __future__ import annotations

from typing import Any

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.components import bluetooth
from homeassistant.components.bluetooth import BluetoothServiceInfoBleak
from homeassistant.config_entries import ConfigFlowResult
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.selector import (
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
)

from .const import (
    CONF_DEVICE_TYPE,
    DEVICE_TYPE_COVER,
    DEVICE_TYPE_THERMOSTAT,
    DEVICE_TYPES,
    DOMAIN,
    LOGGER,
    get_device_id,
    normalize_address,
)
from .gira_ble import GiraBLEClient


class GireaSystem3000ConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Girea System 3000."""

    VERSION = 1
    MINOR_VERSION = 1

    def __init__(self) -> None:
        """Initialize the config flow."""
        self._discovered_address: str | None = None
        self._discovered_name: str | None = None
        self._discovered_type: str = DEVICE_TYPE_COVER

    async def _async_check_device(
        self, address: str, name: str, device_type: str = DEVICE_TYPE_COVER
    ) -> str | None:
        """Connect (and pair) once. Return an error key, or None on success.

        The thermostat is only read from its broadcasts, which needs no
        connection, so it is only checked that Bluetooth sees the device.
        """
        if not bluetooth.async_ble_device_from_address(self.hass, address):
            return "device_not_found"
        if device_type == DEVICE_TYPE_THERMOSTAT:
            return None

        try:
            await GiraBLEClient(self.hass, address, name).async_verify_connection()
        except HomeAssistantError as err:
            LOGGER.debug("Connection test to %s failed: %s", address, err)
            return "cannot_connect"
        except Exception:  # noqa: BLE001 - never let the flow crash on a Bluetooth stack error
            LOGGER.exception("Unexpected error while connecting to Gira device %s", address)
            return "unknown"
        return None

    async def async_step_bluetooth(
        self, discovery_info: BluetoothServiceInfoBleak
    ) -> ConfigFlowResult:
        """Handle the bluetooth discovery step."""
        LOGGER.debug("Bluetooth discovery_info: %s", discovery_info)

        address = normalize_address(discovery_info.address) or discovery_info.address
        await self.async_set_unique_id(get_device_id(address))
        self._abort_if_unique_id_configured()

        self._discovered_address = address
        # The thermostat announces itself with the name "Thermostat" (in pairing mode)
        self._discovered_type = (
            DEVICE_TYPE_THERMOSTAT
            if (discovery_info.name or "").lower().startswith("thermostat")
            else DEVICE_TYPE_COVER
        )
        # A descriptive default name, the user can change it in the next step
        self._discovered_name = f"{discovery_info.name} ({address[-5:].replace(':', '')})"

        self.context["title_placeholders"] = {"name": self._discovered_name}
        return await self.async_step_name()

    async def async_step_name(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Let the user name a discovered device and check that it can be reached."""
        errors: dict[str, str] = {}
        default_name = self._discovered_name

        if user_input is not None:
            name = user_input["name"]
            default_name = name
            if error := await self._async_check_device(
                self._discovered_address, name, self._discovered_type
            ):
                errors["base"] = error
            else:
                return self.async_create_entry(
                    title=name,
                    data={
                        "address": self._discovered_address,
                        "name": name,
                        CONF_DEVICE_TYPE: self._discovered_type,
                    },
                )

        return self.async_show_form(
            step_id="name",
            data_schema=vol.Schema({vol.Required("name", default=default_name): str}),
            errors=errors,
        )

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle the initial step when the user adds a device manually."""
        errors: dict[str, str] = {}
        default_address = ""
        default_name = ""
        default_type = DEVICE_TYPE_COVER

        if user_input is not None:
            default_address = user_input["address"]
            default_name = name = user_input["name"]
            default_type = device_type = user_input[CONF_DEVICE_TYPE]

            if (address := normalize_address(default_address)) is None:
                errors["address"] = "invalid_address"
            else:
                default_address = address
                await self.async_set_unique_id(get_device_id(address))
                self._abort_if_unique_id_configured()

                if error := await self._async_check_device(address, name, device_type):
                    errors["base"] = error
                else:
                    return self.async_create_entry(
                        title=name,
                        data={
                            "address": address,
                            "name": name,
                            CONF_DEVICE_TYPE: device_type,
                        },
                    )

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_DEVICE_TYPE, default=default_type): SelectSelector(
                        SelectSelectorConfig(
                            options=list(DEVICE_TYPES),
                            translation_key=CONF_DEVICE_TYPE,
                            mode=SelectSelectorMode.DROPDOWN,
                        )
                    ),
                    vol.Required("address", default=default_address): str,
                    vol.Required("name", default=default_name): str,
                }
            ),
            errors=errors,
        )
