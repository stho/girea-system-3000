"""Bluetooth LE communication for Gira System 3000 devices."""
import asyncio
import time
from collections.abc import Sequence
from datetime import datetime
from typing import Any

from bleak import BleakClient, BleakError
from bleak_retry_connector import establish_connection
from homeassistant.components import bluetooth
from homeassistant.components.bluetooth import BluetoothServiceInfoBleak
from homeassistant.components.bluetooth.passive_update_coordinator import (
    PassiveBluetoothDataUpdateCoordinator,
)
from homeassistant.core import CALLBACK_TYPE, HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.event import async_call_later

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

# After a command the connection is kept open for a short time, so that follow-up
# commands (e.g. "stop" after "open", or a slider that is moved several times) do
# not have to connect again. 0 switches the reuse off: every command then connects,
# sends and disconnects again.
# Keep this short: while the connection is open, the device may not send position
# broadcasts and other Bluetooth clients (e.g. the Gira app) may not be able to
# connect, and a Bluetooth proxy only has a few connection slots.
IDLE_DISCONNECT_DELAY = 10  # seconds
WRITE_TIMEOUT = 5  # seconds for a command on an already open connection

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
# Prefix of the movement status broadcast (property f7)
MOVEMENT_PREFIX = bytearray.fromhex("F7032001F71001")

# --- Room thermostat broadcasts (reverse engineered, not yet confirmed) ---
# Same layout as above, with other object IDs. The value are two bytes in the KNX
# DPT 9 format (16 bit float), e.g. 0x0C1A = 21.0 degrees.
#   object 0x0141, property 0xFE: measured temperature (assumed)
#   object 0x0065, property 0xFF: target temperature   (assumed)
THERMOSTAT_TEMPERATURE_PREFIX = bytearray.fromhex("F7014101FE1001")
THERMOSTAT_SETPOINT_PREFIX = bytearray.fromhex("F7006501FF1001")
DPT9_INVALID = 0x7FFF


def decode_dpt9(raw: bytes) -> float | None:
    """Decode a KNX DPT 9 (two byte float). Returns None for the "invalid" value.

    Layout: SEEEEMMM MMMMMMMM, value = 0.01 * M * 2**E with M as 11 bit
    two's complement number.
    """
    if len(raw) != 2:
        return None
    value = int.from_bytes(raw, "big")
    if value == DPT9_INVALID:
        return None
    exponent = (value >> 11) & 0x0F
    mantissa = value & 0x07FF
    if value & 0x8000:
        mantissa -= 2048
    return round(0.01 * mantissa * (1 << exponent), 2)


# --- Room thermostat commands (taken from a Bluetooth HCI log of the Gira app) ---
# Notification characteristic: the thermostat answers and reports changes here.
GIRA_NOTIFY_CHARACTERISTIC_UUID = "9769c769-f77a-43ae-8c35-09f0c5245308"
# Write the target temperature: F6 | object 0065 | instance 01 | property F5 | 10 01 | DPT9
THERMOSTAT_SET_SETPOINT_PREFIX = bytearray.fromhex("F6006501F51001")
# Step the target temperature by 0.5 degrees: property F6, value 01 = up, 00 = down
THERMOSTAT_STEP_PREFIX = bytearray.fromhex("F6006501F61001")
SETPOINT_MIN = 7.0
SETPOINT_MAX = 30.0
SETPOINT_STEP = 0.5


def encode_dpt9(value: float) -> bytes:
    """Encode a temperature as KNX DPT 9 (two byte float), the inverse of decode_dpt9."""
    mantissa = round(value * 100)
    exponent = 0
    while not -2048 <= mantissa <= 2047:
        mantissa = round(value * 100 / (1 << (exponent + 1)))
        exponent += 1
        if exponent > 15:
            raise ValueError(f"{value} cannot be encoded as DPT 9")
    raw = (exponent << 11) | (mantissa & 0x07FF)
    if mantissa < 0:
        raw |= 0x8000
    return raw.to_bytes(2, "big")


def generate_setpoint_command(temperature: float) -> bytearray:
    """Generate the command that sets the target temperature of the thermostat."""
    if not SETPOINT_MIN <= temperature <= SETPOINT_MAX:
        raise ValueError(
            f"Temperature must be between {SETPOINT_MIN} and {SETPOINT_MAX} degrees."
        )
    # The thermostat works in steps of 0.5 degrees
    temperature = round(temperature * 2) / 2
    return THERMOSTAT_SET_SETPOINT_PREFIX + encode_dpt9(temperature)


def generate_setpoint_step_command(up: bool) -> bytearray:
    """Generate the command that raises or lowers the target temperature by 0.5."""
    return THERMOSTAT_STEP_PREFIX + (b"\x01" if up else b"\x00")


# --- KNX cEMI property services (see GIRA_SYSTEM_3000_BLUETOOTH.md, section 6) ---
# Frame: [code] [object type, 2 bytes] [instance 01] [property ID]
#        [number of elements (4 bits) and start index (12 bits)] [data]
# The device answers every request with the code minus one (FC -> FB, F6 -> F5)
# and the same header, without data for a write. 0 elements means an error.
CEMI_PROP_READ_REQ = 0xFC
CEMI_PROP_WRITE_REQ = 0xF6

# Time program, "erweitert" mode: index 0 = number of entries (UInt16),
# index 1..n = entries of 10 bytes (see schedule.py)
OBJ_SCHEDULE = 0x03F4
PID_SCHEDULE_ENTRIES = 0x9C
# Mode of the time program: 00 = standard (3 timers, Mo-Fr and Sa+So blocks),
# 01 = erweitert (up to 40 free switch points). Switching it resets the list.
OBJ_SCHEDULE_MODE = 0x0186
PID_SCHEDULE_MODE = 0xA5
SCHEDULE_MODE_EXTENDED = 0x01
# Clock of the device as KNX DPT 19 (date and time), set by the app on connect
OBJ_CLOCK = 0x03E9
PID_CLOCK = 0xFF
# Written by the Gira app when it leaves the time program; the meaning is not
# known (maybe "apply"). It is sent the same way after writing the schedule.
SCHEDULE_DONE_COMMAND = bytearray.fromhex("F6C35A0105100102") + bytes(8)

RESPONSE_TIMEOUT = 5  # seconds to wait for the answer to a property request


def generate_property_frame(
    code: int, object_type: int, property_id: int, index: int = 1, data: bytes = b""
) -> bytearray:
    """Generate a cEMI property read or write frame for one element."""
    if not 0 <= index <= 0x0FFF:
        raise ValueError(f"Index {index} is out of range.")
    return (
        bytearray((code,))
        + object_type.to_bytes(2, "big")
        + b"\x01"
        + bytes((property_id,))
        + ((1 << 12) | index).to_bytes(2, "big")
        + data
    )


def read_frame(object_type: int, property_id: int, index: int = 1) -> bytearray:
    """Frame that reads one element of a property."""
    return generate_property_frame(CEMI_PROP_READ_REQ, object_type, property_id, index)


def write_frame(
    object_type: int, property_id: int, index: int, data: bytes
) -> bytearray:
    """Frame that writes one element of a property."""
    return generate_property_frame(
        CEMI_PROP_WRITE_REQ, object_type, property_id, index, data
    )


def response_key(frame: bytes) -> tuple[int, bytes, int] | None:
    """Key that pairs a request with its answer: answer code, object, instance,
    property and start index (the number of elements is 0 in an error answer).
    """
    if len(frame) < 7:
        return None
    code = frame[0]
    if code in (CEMI_PROP_READ_REQ, CEMI_PROP_WRITE_REQ):
        code -= 1
    return code, bytes(frame[1:5]), int.from_bytes(frame[5:7], "big") & 0x0FFF


def encode_dpt19(when: datetime) -> bytes:
    """Encode date and time as KNX DPT 19 (8 bytes), as the Gira app sends it.

    Day of week 1 = Monday ... 7 = Sunday. Both flag bytes are 0 (as in the app).
    """
    return bytes(
        (
            when.year - 1900,
            when.month,
            when.day,
            (when.isoweekday() << 5) | when.hour,
            when.minute,
            when.second,
            0,
            0,
        )
    )


def generate_clock_command(when: datetime) -> bytearray:
    """Command that sets the clock of the thermostat."""
    return write_frame(OBJ_CLOCK, PID_CLOCK, 1, encode_dpt19(when))


def generate_schedule_write_commands(
    entries: list[bytes], set_mode: bool
) -> list[bytearray]:
    """Commands that replace the time program with the given encoded entries.

    The order is the one of the Gira app: (switch to the extended mode,) clear
    the list by setting the count to 0, append the entries one by one, and
    finish with the command the app sends when it leaves the time program.
    """
    commands = []
    if set_mode:
        # Switching the mode resets the list, so it has to happen first
        commands.append(
            write_frame(
                OBJ_SCHEDULE_MODE, PID_SCHEDULE_MODE, 1, bytes((SCHEDULE_MODE_EXTENDED,))
            )
        )
    commands.append(write_frame(OBJ_SCHEDULE, PID_SCHEDULE_ENTRIES, 0, b"\x00\x00"))
    commands.extend(
        write_frame(OBJ_SCHEDULE, PID_SCHEDULE_ENTRIES, index, entry)
        for index, entry in enumerate(entries, start=1)
    )
    commands.append(SCHEDULE_DONE_COMMAND)
    return commands


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
        self.data: dict[str, Any] | None = None
        self._last_advertisement: tuple[dict[int, str], dict[str, str]] | None = None
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

        # Log every change in the advertisements of the device, also the ones that
        # are not parsed below. This shows what the device sends while it moves (and
        # when), e.g. whether there is a movement status besides the position. The
        # callback is also called for repeated identical advertisements, so only
        # changes are logged to keep the log readable.
        advertisement = (
            {k: v.hex() for k, v in service_info.manufacturer_data.items()},
            {k: v.hex() for k, v in service_info.service_data.items()},
        )
        if advertisement != self._last_advertisement:
            self._last_advertisement = advertisement
            LOGGER.debug(
                "Advertisement changed for %s via %s (RSSI %s): manufacturer_data=%s service_data=%s",
                self._device_name,
                service_info.source,
                service_info.rssi,
                *advertisement,
            )

        manufacturer_data = service_info.manufacturer_data.get(GIRA_MANUFACTURER_ID)
        if not manufacturer_data:
            return

        # Each broadcast carries one property (position, movement status, ...).
        # Merge it into the known data instead of replacing everything.
        data = dict(self.data or {})
        changed = False

        position_byte = self._read_property(manufacturer_data, BROADCAST_PREFIX)
        if position_byte is not None:
            data["position"] = round(100 * (255 - position_byte) / 255)
            data["position_updated"] = time.monotonic()
            changed = True
            LOGGER.debug(
                "Gira position broadcast from %s. Raw data: %s, Position byte: %s, HA Position: %s%%",
                self._device_name,
                manufacturer_data.hex(),
                position_byte,
                data["position"],
            )

        movement_byte = self._read_property(manufacturer_data, MOVEMENT_PREFIX)
        if movement_byte is not None:
            # 0-1: stopped, >1: moving (see GIRA_SYSTEM_3000_BLUETOOTH.md)
            data["moving"] = movement_byte > 1
            # Lets the entity tell a new broadcast from an old, repeated value
            data["moving_updated"] = time.monotonic()
            changed = True
            LOGGER.debug(
                "Gira movement broadcast from %s. Raw data: %s, status byte: %s",
                self._device_name,
                manufacturer_data.hex(),
                movement_byte,
            )

        # Room thermostat: temperatures as DPT 9 values (see decode_dpt9)
        for key, prefix in (
            ("temperature", THERMOSTAT_TEMPERATURE_PREFIX),
            ("setpoint", THERMOSTAT_SETPOINT_PREFIX),
        ):
            raw = self._read_bytes(manufacturer_data, prefix, 2)
            if raw is None:
                continue
            value = decode_dpt9(raw)
            if value is None:
                continue
            data[key] = value
            changed = True
            LOGGER.debug(
                "Gira thermostat broadcast from %s. Raw data: %s, %s: %s",
                self._device_name,
                manufacturer_data.hex(),
                key,
                value,
            )

        if not changed:
            return

        self.data = data
        # The base class marks the device available and notifies the listeners.
        super()._async_handle_bluetooth_event(service_info, change)

    @staticmethod
    def _read_bytes(
        manufacturer_data: bytes, prefix: bytearray, length: int
    ) -> bytes | None:
        """Return the `length` bytes following the prefix, or None if not present."""
        prefix_index = manufacturer_data.find(prefix)
        if prefix_index == -1:
            return None
        start = prefix_index + len(prefix)
        if len(manufacturer_data) < start + length:
            return None
        return bytes(manufacturer_data[start : start + length])

    @staticmethod
    def _read_property(manufacturer_data: bytes, prefix: bytearray) -> int | None:
        """Return the value byte following the prefix, or None if not present."""
        prefix_index = manufacturer_data.find(prefix)
        if prefix_index == -1:
            return None
        value_index = prefix_index + len(prefix)
        if len(manufacturer_data) <= value_index:
            LOGGER.debug("Not enough data after broadcast prefix")
            return None
        return manufacturer_data[value_index]


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
    """Manages the Bluetooth LE connection and command sending for a Gira device.

    A connection is made on demand and kept open for IDLE_DISCONNECT_DELAY seconds
    after the last command, so that follow-up commands are sent faster.
    """

    def __init__(
        self, hass: HomeAssistant, address: str, name: str, thermostat: bool = False
    ) -> None:
        """Initialize the client."""
        self.hass = hass
        self.address = address
        self.name = name
        # The thermostat app enables notifications before it writes; do the same
        self._thermostat = thermostat
        self._notify_client: BleakClient | None = None
        self._client: BleakClient | None = None
        self._lock = asyncio.Lock()
        self._idle_timer: CALLBACK_TYPE | None = None
        self._last_used = 0.0
        # Requests waiting for their answer from the thermostat, see response_key
        self._pending: dict[tuple[int, bytes, int], asyncio.Future[bytes]] = {}

    async def send_command(self, command: bytearray) -> None:
        """Send a command, using the open connection if there is one.

        Raises HomeAssistantError if the device cannot be reached, so the
        failure is shown to the user instead of being swallowed.
        """
        await self.async_exchange([command])

    async def async_exchange(
        self, commands: Sequence[bytearray], confirm: bool = False
    ) -> list[bytes | None]:
        """Send several commands over one connection, one after the other.

        With confirm=True every command is a cEMI property request and the
        answer of the thermostat is awaited (only possible for the thermostat,
        which has notifications enabled). Returns the data of the answers (None
        without confirm). Raises HomeAssistantError on failure.
        """
        if confirm and not self._thermostat:
            raise ValueError("Only the thermostat answers property requests.")
        results: list[bytes | None] = []
        async with self._lock:
            self._cancel_idle_timer()
            try:
                for command in commands:
                    sent, result = await self._async_write_open_connection(
                        command, confirm
                    )
                    if not sent:
                        result = await self._async_connect_and_write(command, confirm)
                    results.append(result)
            finally:
                self._last_used = time.monotonic()
                if self._client is not None:
                    self._schedule_idle_disconnect()
        return results

    async def _async_write_open_connection(
        self, command: bytearray, confirm: bool
    ) -> tuple[bool, bytes | None]:
        """Try to send the command over the open connection.

        Returns (True, answer) if the command was sent. Returns (False, None) if
        there is no usable connection (the caller then connects again). A
        connection that went stale is dropped. Note that a write whose
        confirmation got lost is sent again over the new connection; the
        commands of the cover and the property writes can safely be repeated.
        """
        client = self._client
        if client is None:
            return False, None
        if not client.is_connected:
            await self._async_drop_connection()
            return False, None

        try:
            started = time.monotonic()
            async with asyncio.timeout(WRITE_TIMEOUT + (RESPONSE_TIMEOUT if confirm else 0)):
                result = await self._async_write(client, command, confirm)
        except (BleakError, TimeoutError) as e:
            LOGGER.debug(
                "The open connection to %s did not work (%s), connecting again.", self.name, e
            )
            await self._async_drop_connection()
            return False, None

        LOGGER.debug(
            "Command sent over the open connection to %s in %.2f s.",
            self.name,
            time.monotonic() - started,
        )
        return True, result

    async def _async_connect_and_write(
        self, command: bytearray, confirm: bool = False
    ) -> bytes | None:
        """Connect to the device and send the command.

        The connection is kept open afterwards if the reuse is switched on.
        """
        device = bluetooth.async_ble_device_from_address(self.hass, self.address)
        if not device:
            raise _error("device_not_found", name=self.name, address=self.address)

        LOGGER.debug("Connecting to %s (%s) to send a command.", self.name, self.address)

        client = None
        keep_open = False
        try:
            async with asyncio.timeout(COMMAND_TIMEOUT):
                started = time.monotonic()
                client = await establish_connection(
                    BleakClient,
                    device,
                    self.name,
                    disconnected_callback=self._on_disconnected,
                    pair=True,
                    max_attempts=MAX_CONNECT_ATTEMPTS,
                )
                connected = time.monotonic()
                result = await self._async_write(client, command, confirm)
            LOGGER.debug(
                "Command sent to %s: connecting took %.2f s, writing %.2f s.",
                self.name,
                connected - started,
                time.monotonic() - connected,
            )
            keep_open = IDLE_DISCONNECT_DELAY > 0
            return result
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
            if keep_open:
                self._client = client
            else:
                await self._async_disconnect(client)

    async def _async_write(
        self, client: BleakClient, command: bytearray, confirm: bool = False
    ) -> bytes | None:
        """Write the command and wait until the device confirmed it.

        With confirm=True also wait for the cEMI answer and return its data.
        """
        if self._thermostat and self._notify_client is not client:
            await client.start_notify(
                GIRA_NOTIFY_CHARACTERISTIC_UUID, self._on_notification
            )
            self._notify_client = client

        key = response_key(command) if confirm else None
        future: asyncio.Future[bytes] | None = None
        if key is not None:
            future = asyncio.get_running_loop().create_future()
            self._pending[key] = future
        try:
            LOGGER.debug("Sending command: %s", command.hex())
            # response=True is crucial: the command is only done when the device confirmed it
            await client.write_gatt_char(
                GIRA_COMMAND_CHARACTERISTIC_UUID, command, response=True
            )
            if future is None:
                return None
            async with asyncio.timeout(RESPONSE_TIMEOUT):
                return await future
        finally:
            if key is not None and self._pending.get(key) is future:
                del self._pending[key]

    def _on_notification(self, _characteristic: Any, data: bytearray) -> None:
        """Hand answers to the waiting requests and log everything else."""
        data = bytes(data)
        LOGGER.debug("Notification from %s: %s", self.name, data.hex())
        key = response_key(data)
        future = self._pending.pop(key, None) if key else None
        if future is None or future.done():
            return
        if data[5] >> 4 == 0:
            # No element: the device refused the request (data = error code)
            future.set_exception(
                _error("property_error", name=self.name, frame=data.hex())
            )
        else:
            future.set_result(data[7:])

    def _on_disconnected(self, client: BleakClient) -> None:
        """Forget the connection when the device or the adapter closed it."""
        if self._notify_client is client:
            self._notify_client = None
            # Answers can no longer arrive; let the requests fail right away
            for future in self._pending.values():
                if not future.done():
                    future.set_exception(BleakError("Disconnected"))
            self._pending.clear()
        if self._client is client:
            LOGGER.debug("The connection to %s was closed.", self.name)
            self._client = None

    def _schedule_idle_disconnect(self) -> None:
        """Close the connection after IDLE_DISCONNECT_DELAY seconds without a command."""
        self._cancel_idle_timer()
        self._idle_timer = async_call_later(
            self.hass, IDLE_DISCONNECT_DELAY, self._async_idle_disconnect
        )

    def _cancel_idle_timer(self) -> None:
        """Cancel the pending idle disconnect, if any."""
        if self._idle_timer is not None:
            self._idle_timer()
            self._idle_timer = None

    async def _async_idle_disconnect(self, _now: object) -> None:
        """Close the connection that was not used for a while."""
        self._idle_timer = None
        async with self._lock:
            # A command that ran while this waited for the lock has scheduled its
            # own timer. The margin keeps the timer from skipping its own job
            # because of clock rounding, which would leave the connection open.
            if time.monotonic() - self._last_used < IDLE_DISCONNECT_DELAY - 1:
                return
            LOGGER.debug("Closing the idle connection to %s.", self.name)
            await self._async_drop_connection()

    async def _async_drop_connection(self) -> None:
        """Disconnect and forget the open connection."""
        client, self._client = self._client, None
        await self._async_disconnect(client)

    async def async_shutdown(self) -> None:
        """Close the connection, e.g. when the config entry is unloaded."""
        self._cancel_idle_timer()
        async with self._lock:
            await self._async_drop_connection()

    async def async_verify_connection(self) -> None:
        """Connect (and pair) once without sending a command, then disconnect.

        Used by the config flow, so that a wrong address or a device that is not
        in pairing mode is reported while the device is being added, instead of
        at the first button press. Raises HomeAssistantError on failure.
        """
        device = bluetooth.async_ble_device_from_address(self.hass, self.address)
        if not device:
            raise _error("device_not_found", name=self.name, address=self.address)

        async with self._lock:
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
            LOGGER.debug("Disconnecting from %s (%s).", self.name, self.address)
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

    async def set_setpoint(self, temperature: float) -> None:
        """Set the target temperature of the room thermostat."""
        await self.send_command(generate_setpoint_command(temperature))

    async def async_set_clock(self, when: datetime) -> None:
        """Set the clock of the thermostat (local time)."""
        await self.async_exchange([generate_clock_command(when)], confirm=True)

    async def async_read_schedule(self) -> tuple[bool, list[bytes]]:
        """Read the time program of the thermostat.

        Returns whether the extended mode is set and the raw entries (10 bytes
        each). In the standard mode the entries follow the fixed layout of the
        Gira app (3 timers with Mo-Fr and Sa+So blocks).
        """
        mode, count = await self.async_exchange(
            [
                read_frame(OBJ_SCHEDULE_MODE, PID_SCHEDULE_MODE),
                read_frame(OBJ_SCHEDULE, PID_SCHEDULE_ENTRIES, 0),
            ],
            confirm=True,
        )
        if not mode or not count or len(count) < 2:
            raise _error("schedule_read_failed", name=self.name)
        number = int.from_bytes(count[:2], "big")
        entries = await self.async_exchange(
            [
                read_frame(OBJ_SCHEDULE, PID_SCHEDULE_ENTRIES, index)
                for index in range(1, number + 1)
            ],
            confirm=True,
        )
        return mode[0] == SCHEDULE_MODE_EXTENDED, [entry or b"" for entry in entries]

    async def async_write_schedule(self, entries: list[bytes], when: datetime) -> None:
        """Replace the time program with the given encoded entries.

        Switches to the extended mode if needed and sets the clock, so the
        switch points apply at the right time.
        """
        (mode,) = await self.async_exchange(
            [read_frame(OBJ_SCHEDULE_MODE, PID_SCHEDULE_MODE)], confirm=True
        )
        commands = [generate_clock_command(when)]
        commands += generate_schedule_write_commands(
            entries, set_mode=not mode or mode[0] != SCHEDULE_MODE_EXTENDED
        )
        await self.async_exchange(commands, confirm=True)
