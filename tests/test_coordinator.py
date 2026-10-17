"""Tests for parsing the broadcasts of the device."""
import types
import unittest

from tests import _stubs

gira_ble = _stubs.load("gira_ble")

ADDRESS = "AA:BB:CC:DD:EE:FF"
DEVICE_BYTES = "01020304"  # device specific bytes in front of the property
POSITION = "F7032001F61001"
MOVEMENT = "F7032001F71001"
SLATS = "F7032001F51001"


def make_coordinator():
    coordinator = gira_ble.GiraPassiveBluetoothDataUpdateCoordinator.__new__(
        gira_ble.GiraPassiveBluetoothDataUpdateCoordinator
    )
    coordinator.address = ADDRESS
    coordinator._device_name = "test"
    coordinator.data = None
    coordinator._last_advertisement = None
    coordinator.notified = 0
    return coordinator


def receive(coordinator, payload_hex, address=ADDRESS, manufacturer_id=1412):
    service_info = types.SimpleNamespace(
        device=types.SimpleNamespace(address=address),
        manufacturer_data={manufacturer_id: bytes.fromhex(payload_hex)},
        service_data={},
        source="proxy",
        rssi=-60,
    )
    coordinator._async_handle_bluetooth_event(service_info, None)


class CoordinatorTest(unittest.TestCase):
    def setUp(self):
        self.coordinator = make_coordinator()

    def test_position_conversion(self):
        for byte, expected in (("00", 100), ("ff", 0), ("80", 50)):
            receive(self.coordinator, DEVICE_BYTES + POSITION + byte)
            self.assertEqual(self.coordinator.data["position"], expected)

    def test_movement_status(self):
        for byte, moving in (("03", True), ("02", True), ("01", False), ("00", False)):
            receive(self.coordinator, DEVICE_BYTES + MOVEMENT + byte)
            self.assertEqual(self.coordinator.data["moving"], moving)

    def test_properties_are_merged(self):
        receive(self.coordinator, DEVICE_BYTES + POSITION + "ff")
        receive(self.coordinator, DEVICE_BYTES + MOVEMENT + "03")
        self.assertEqual(self.coordinator.data["position"], 0)
        self.assertTrue(self.coordinator.data["moving"])
        self.assertEqual(self.coordinator.notified, 2)

    def test_timestamps_change_with_each_broadcast(self):
        receive(self.coordinator, DEVICE_BYTES + MOVEMENT + "03")
        first = self.coordinator.data["moving_updated"]
        receive(self.coordinator, DEVICE_BYTES + MOVEMENT + "03")
        self.assertGreater(self.coordinator.data["moving_updated"], first)

    def test_ignored_broadcasts(self):
        receive(self.coordinator, DEVICE_BYTES + SLATS + "05")  # slats: not used
        receive(self.coordinator, DEVICE_BYTES + POSITION + "ff", address="11:22:33:44:55:66")
        receive(self.coordinator, DEVICE_BYTES + POSITION + "ff", manufacturer_id=76)
        receive(self.coordinator, DEVICE_BYTES + POSITION)  # value byte missing
        self.assertIsNone(self.coordinator.data)
        self.assertEqual(self.coordinator.notified, 0)


if __name__ == "__main__":
    unittest.main()
