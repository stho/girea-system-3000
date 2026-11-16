"""Tests for the room thermostat broadcasts (temperatures as KNX DPT 9)."""
import unittest

from tests import _stubs
from tests.test_coordinator import DEVICE_BYTES, POSITION, make_coordinator, receive

gira_ble = _stubs.load("gira_ble")

TEMPERATURE = "F7014101FE1001"
SETPOINT = "F7006501FF1001"


class Dpt9Test(unittest.TestCase):
    def test_known_values(self):
        for raw, expected in (
            ("0c1a", 21.0),
            ("0c04", 20.56),
            ("0c21", 21.14),
            ("0000", 0.0),
            ("860c", -5.0),  # sign bit and negative mantissa
            ("0064", 1.0),
            # values from the notification logs (device buttons and Gira app)
            ("07d0", 20.0),
            ("0c01", 20.5),
            ("0c4c", 22.0),
            ("0c65", 22.5),
            ("0c7e", 23.0),
            ("0c97", 23.5),
            ("0cb0", 24.0),
            ("0cc9", 24.5),
            ("0ce2", 25.0),
            ("07f2", 20.34),
            ("02bc", 7.0),
        ):
            self.assertEqual(gira_ble.decode_dpt9(bytes.fromhex(raw)), expected, raw)

    def test_invalid_value_and_length(self):
        self.assertIsNone(gira_ble.decode_dpt9(bytes.fromhex("7fff")))
        self.assertIsNone(gira_ble.decode_dpt9(b"\x0c"))
        self.assertIsNone(gira_ble.decode_dpt9(b"\x0c\x1a\x00"))


class ThermostatBroadcastTest(unittest.TestCase):
    def setUp(self):
        self.coordinator = make_coordinator()

    def test_captured_broadcasts(self):
        # Payloads as sent by the thermostat (manufacturer data after the company ID)
        receive(self.coordinator, "4a090115f7014101fe10010c04")
        receive(self.coordinator, "4a090115f7006501ff10010c1a")
        self.assertEqual(self.coordinator.data["temperature"], 20.56)
        self.assertEqual(self.coordinator.data["setpoint"], 21.0)
        self.assertEqual(self.coordinator.notified, 2)

    def test_values_are_merged_and_updated(self):
        receive(self.coordinator, DEVICE_BYTES + TEMPERATURE + "0c04")
        receive(self.coordinator, DEVICE_BYTES + SETPOINT + "0c1a")
        receive(self.coordinator, DEVICE_BYTES + TEMPERATURE + "0c0b")
        self.assertEqual(self.coordinator.data["temperature"], 20.7)
        self.assertEqual(self.coordinator.data["setpoint"], 21.0)

    def test_incomplete_and_invalid_values_are_ignored(self):
        receive(self.coordinator, DEVICE_BYTES + TEMPERATURE + "0c")  # one byte only
        receive(self.coordinator, DEVICE_BYTES + SETPOINT + "7fff")  # invalid
        self.assertIsNone(self.coordinator.data)
        self.assertEqual(self.coordinator.notified, 0)

    def test_shutter_broadcasts_do_not_touch_thermostat_values(self):
        receive(self.coordinator, DEVICE_BYTES + POSITION + "ff")
        self.assertNotIn("temperature", self.coordinator.data)
        self.assertNotIn("setpoint", self.coordinator.data)


if __name__ == "__main__":
    unittest.main()
