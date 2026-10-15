"""Bluetooth LE communication for Gira System 3000 devices."""
import asyncio

from bleak import BleakClient, BleakError
from bleak_retry_connector import establish_connection

from homeassistant.components import bluetooth
from homeassistant.components.bluetooth import BluetoothServiceInfoBleak
from homeassistant.components.bluetooth.passive_update_coordinator import (
    PassiveBluetoothDataUpdateCoordinator,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError

from .const import DOMAIN, LOGGER

# Define the correct GATT Characteristic UUID.
GIRA_COMMAND_CHARACTERISTIC_UUID = "97696341-f77a-43ae-8c35-09f0c5245308"

# establish_connection() has no overall time limit: every attempt may take up
# to 20 s (not configurable), plus a pause between attempts. With an
# unreachable device or Bluetooth proxy a command can therefore hang for a
# minute or more before the error appears. These values limit that.
MAX_CONNECT_ATTEMPTS = 2
COMMAND_TIMEOUT = 20  # seconds for connecting and sending one command
DISCONNECT_TIMEOUT = 5  # seconds

# --- Constants for Gira Command Generation ---
# Basic command structure prefix
COMMAND_PREFIX = bytearray.fromhex("F6032001")

# Suffix constant often preceding the actual value
COMMAND_SUFFIX = bytearray.fromhex("1001")

# Property IDs for different command types
PROPERTY_ID_MOVE = 0xFF # For Up/Down commands
PROPERTY_ID_STOP = 0xFD # For Stop command
PROPERTY_ID_STEP = 0xFE # For Step Up/Down commands
PROPERTY_ID_SET_POSITION = 0xFC # For Absolute Position (Percentage)

# Values for commands
VALUE_UP = 0x00
VALUE_DOWN = 0x01
VALUE_STOP = 0x00 # Stop command uses 0x00 as its value


# --- Constants for Gira Broadcast Parsing ---
GIRA_MANUFACTURER_ID = 1412
# The correct, full prefix for a position broadcast
BROADCAST_PREFIX = bytearray.fromhex("F7032001F61001")


def _error(key: str, **placeholders: object) -> HomeAssistantError:
    """Return a HomeAssistantError whose text is translated by Home Assistant.

    The texts are in translations/<lang>.json under "exceptions". Without a
    translation key the message would always be English, even though Home
    Assistant adds its own text in the user's language around it.
    """
    return HomeAssistantError(
        translation_domain=DOMAIN,
        translation_key=key,
        translation_placeholders={k: str(v) for k, v in placeholders.items()},
    )


class GiraPassiveBluetoothDataUpdateCoordinator(PassiveBluetoothDataUpdateCoordinator):
    """Coordinator for receiving passive BLE broadcasts from Gira shutters."""

    def __init__(self, hass: HomeAssistant, address: str, name: str):
        """Initialize the coordinator."""
        super().__init__(
            hass,
            LOGGER,
            address=address,
            mode=bluetooth.BluetoothScanningMode.PASSIVE,
            connectable=False,
        )
        self._device_name = name  # Store name separately since 'name' property is read-only
        # The base class does not define `data`. Entities read it, so it has to
        # exist before the first broadcast (or an "unavailable" event) arrives.
        self.data: dict[str, int] | None = None
        LOGGER.debug("Created coordinator instance for %s (%s)", name, address)

    @callback
    def _async_handle_unavailable(
        self, service_info: BluetoothServiceInfoBleak
    ) -> None:
        """Handle the device going unavailable."""
        LOGGER.debug("Handle unavailable for %s (%s)", self._device_name, self.address)
        # The base class marks the device unavailable and notifies the listeners.
        super()._async_handle_unavailable(service_info)

    @callback
    def _async_handle_bluetooth_event(
        self,
        service_info: BluetoothServiceInfoBleak,
        change: bluetooth.BluetoothChange,
    ) -> None:
        """Handle a Bluetooth advertisement of the device."""
        # Check if this event is for our device
        if service_info.device.address.upper() != self.address.upper():
            return

        manufacturer_data = service_info.manufacturer_data.get(GIRA_MANUFACTURER_ID)
        if not manufacturer_data:
            return

        # Check if the BROADCAST_PREFIX is anywhere within the manufacturer_data
        prefix_index = manufacturer_data.find(BROADCAST_PREFIX)
        if prefix_index == -1:
            return

        # Ensure we have enough bytes after the prefix to read the position
        position_index = prefix_index + len(BROADCAST_PREFIX)
        if len(manufacturer_data) <= position_index:
            LOGGER.debug("Not enough data after broadcast prefix")
            return

        # Extract the position byte, which is 1 byte after the prefix
        position_byte = manufacturer_data[position_index]
        ha_position = round(100 * (255 - position_byte) / 255)

        LOGGER.debug(
            "Gira broadcast received from %s. Raw data: %s, Position byte: %s, HA Position: %s%%",
            self._device_name,
            manufacturer_data.hex(),
            position_byte,
            ha_position,
        )

        self.data = {"position": ha_position}
        # The base class marks the device available and notifies the listeners.
        super()._async_handle_bluetooth_event(service_info, change)



def _generate_command(property_id: int, value: int) -> bytearray:
    """Generates the full command byte array from its parts."""
    return (
        COMMAND_PREFIX
        + property_id.to_bytes(1, 'big')
        + COMMAND_SUFFIX
        + value.to_bytes(1, 'big')
    )

def generate_position_command(percentage: int) -> bytearray:
    """Generates the command for setting absolute blinds position."""
    if not 0 <= percentage <= 100:
        raise ValueError("Percentage must be between 0 and 100.")
    per_to_byte = (100 - percentage) * 255 // 100
    return _generate_command(PROPERTY_ID_SET_POSITION, per_to_byte)


class GiraBLEClient:
    """Manages the Bluetooth LE connection and command sending for a Gira device."""

    def __init__(self, hass: HomeAssistant, address: str, name: str) -> None:
        """Initialize the client."""
        self.hass = hass
        self.address = address
        self.name = name
        self._client: BleakClient | None = None
        self._is_connecting = asyncio.Lock()

    async def send_command(self, command: bytearray) -> None:
        """
        Connect to the device, send a command, and then disconnect.
        This is a single-shot, connect-on-demand method.

        Raises HomeAssistantError if the device cannot be reached, so the
        failure is shown to the user instead of being swallowed.
        """
        async with self._is_connecting:
            if self._client and self._client.is_connected:
                LOGGER.debug("Client already connected, sending command directly.")
                try:
                    # Log the command before sending it
                    LOGGER.debug("Sending command: %s", command.hex())
                    # Changed response to False
                    await self._client.write_gatt_char(GIRA_COMMAND_CHARACTERISTIC_UUID, command, response=False)
                    return
                except (BleakError, asyncio.TimeoutError) as e:
                    LOGGER.warning("Failed to send command to connected device: %s", e)
                    # Fall through to attempt a reconnect
                    await self._client.disconnect()
                    self._client = None

            LOGGER.debug("Attempting to connect to %s (%s) to send command.", self.name, self.address)

            device = bluetooth.async_ble_device_from_address(self.hass, self.address)
            if not device:
                raise _error("device_not_found", name=self.name, address=self.address)

            client = None
            try:
                async with asyncio.timeout(COMMAND_TIMEOUT):
                    client = await establish_connection(
                        BleakClient,
                        device,
                        self.name,
                        pair=True,
                        max_attempts=MAX_CONNECT_ATTEMPTS,
                    )
                    self._client = client
                    LOGGER.info("Successfully connected to %s (%s) and sending command.", self.name, self.address)

                    # Log the command before sending it
                    LOGGER.debug("Sending command: %s", command.hex())

                    # Send the command, reponse=True is crucial
                    await client.write_gatt_char(GIRA_COMMAND_CHARACTERISTIC_UUID, command, response=True)

                LOGGER.info("Command sent successfully to %s.", self.name)
            except TimeoutError as e:
                raise _error(
                    "command_timeout",
                    name=self.name,
                    address=self.address,
                    timeout=COMMAND_TIMEOUT,
                ) from e
            except BleakError as e:
                raise _error(
                    "command_failed", name=self.name, address=self.address, error=e
                ) from e
            finally:
                await self._async_disconnect(client)
                self._client = None

    async def async_verify_connection(self) -> None:
        """Connect (and pair) once without sending a command, then disconnect.

        Used by the config flow, so that a wrong address or a device that is not
        in pairing mode is reported while the device is being added, instead of
        at the first button press. Raises HomeAssistantError on failure.
        """
        device = bluetooth.async_ble_device_from_address(self.hass, self.address)
        if not device:
            raise _error("device_not_found", name=self.name, address=self.address)

        async with self._is_connecting:
            client = None
            try:
                async with asyncio.timeout(COMMAND_TIMEOUT):
                    client = await establish_connection(
                        BleakClient,
                        device,
                        self.name,
                        pair=True,
                        max_attempts=MAX_CONNECT_ATTEMPTS,
                    )
                LOGGER.debug("Connection test to %s (%s) succeeded.", self.name, self.address)
            except TimeoutError as e:
                raise _error(
                    "command_timeout",
                    name=self.name,
                    address=self.address,
                    timeout=COMMAND_TIMEOUT,
                ) from e
            except BleakError as e:
                raise _error(
                    "connect_failed", name=self.name, address=self.address, error=e
                ) from e
            finally:
                await self._async_disconnect(client)

    async def _async_disconnect(self, client: BleakClient | None) -> None:
        """Disconnect after use. A failing disconnect is logged, never raised.

        The operation was already handled at this point, so a failing
        disconnect must not turn it into an error (or hide the real one).
        """
        if client and client.is_connected:
            LOGGER.info("Disconnecting from %s (%s).", self.name, self.address)
            try:
                async with asyncio.timeout(DISCONNECT_TIMEOUT):
                    await client.disconnect()
            except (BleakError, TimeoutError) as e:
                LOGGER.debug("Disconnect from %s failed: %s", self.name, e)

    async def send_up_command(self) -> None:
        """Send the command to raise the shutter."""
        await self.send_command(_generate_command(PROPERTY_ID_MOVE, VALUE_UP))

    async def send_down_command(self) -> None:
        """Send the command to lower the shutter."""
        await self.send_command(_generate_command(PROPERTY_ID_MOVE, VALUE_DOWN))

    async def send_stop_command(self) -> None:
        """Send the command to stop the shutter."""
        await self.send_command(_generate_command(PROPERTY_ID_STOP, VALUE_STOP))

    async def send_step_up_command(self) -> None:
        """Send the command to step the shutter up."""
        await self.send_command(_generate_command(PROPERTY_ID_STEP, VALUE_UP))

    async def send_step_down_command(self) -> None:
        """Send the command to step the shutter down."""
        await self.send_command(_generate_command(PROPERTY_ID_STEP, VALUE_DOWN))

    async def set_absolute_position(self, percentage: int) -> None:
        """Set the absolute position of the blinds (0-100%)."""
        command = generate_position_command(percentage)
        await self.send_command(command)
