"""Tests for MAC handling and the command bytes."""
import unittest

from tests import _stubs

const = _stubs.load("const")
gira_ble = _stubs.load("gira_ble")


class NormalizeAddressTest(unittest.TestCase):
    def test_accepted_spellings(self):
        for value in ("aa:bb:cc:dd:ee:ff", "AA-BB-CC-DD-EE-FF", " aabbccddeeff "):
            self.assertEqual(const.normalize_address(value), "AA:BB:CC:DD:EE:FF")

    def test_invalid(self):
        for value in ("", "AA:BB", "GG:BB:CC:DD:EE:FF", "AA:BB:CC:DD:EE:FF:00"):
            self.assertIsNone(const.normalize_address(value))

    def test_device_id_is_independent_of_spelling(self):
        self.assertEqual(
            const.get_device_id("AA:BB:CC:DD:EE:FF"),
            const.get_device_id("aa-bb-cc-dd-ee-ff"),
        )


class CommandTest(unittest.TestCase):
    def test_move_and_stop(self):
        gen = gira_ble._generate_command
        self.assertEqual(gen(0xFF, 0).hex(), "f6032001ff100100")  # up
        self.assertEqual(gen(0xFF, 1).hex(), "f6032001ff100101")  # down
        self.assertEqual(gen(0xFD, 0).hex(), "f6032001fd100100")  # stop

    def test_position_command(self):
        gen = gira_ble.generate_position_command
        self.assertEqual(gen(100).hex(), "f6032001fc100100")  # fully open
        self.assertEqual(gen(0).hex(), "f6032001fc1001ff")  # fully closed
        self.assertEqual(gen(50).hex(), "f6032001fc10017f")

    def test_position_out_of_range(self):
        for value in (-1, 101):
            with self.assertRaises(ValueError):
                gira_ble.generate_position_command(value)


if __name__ == "__main__":
    unittest.main()
