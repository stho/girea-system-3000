"""Tests for the week schedule of the room thermostat.

The byte strings are taken from Bluetooth HCI logs of the Gira app (2026-11-15),
see GIRA_SYSTEM_3000_BLUETOOTH.md.
"""
import asyncio
import unittest
from datetime import datetime

from tests import _stubs

gira_ble = _stubs.load("gira_ble")
schedule = _stubs.load("schedule")

DaySchedule = schedule.DaySchedule
Entry = schedule.Entry
MONDAY, WEDNESDAY, SATURDAY, SUNDAY = 1, 1 << 2, 1 << 5, 1 << 6
WORKDAYS = 0x1F
ALL_DAYS = 0x7F


def encode(entry):
    return schedule.encode_entry(entry, gira_ble.encode_dpt9).hex()


def decode(raw):
    return schedule.decode_entry(bytes.fromhex(raw), gira_ble.decode_dpt9)


class ParseDayTest(unittest.TestCase):
    def test_example(self):
        day = schedule.parse_day("5,6:00,21,18:00,5")
        self.assertEqual(day, DaySchedule(5.0, ((360, 21.0), (1080, 5.0))))
        self.assertEqual(schedule.format_day(day), "5,06:00,21,18:00,5")

    def test_single_value_decimals_and_spaces(self):
        self.assertEqual(schedule.parse_day(" 19.5 "), DaySchedule(19.5))
        self.assertEqual(
            schedule.format_day(schedule.parse_day("18, 06:07 ,19.5")), "18,06:07,19.5"
        )

    def test_any_minute_and_low_temperatures(self):
        day = schedule.parse_day("5,06:07,5.5,23:59,30")
        self.assertEqual(day.points, ((367, 5.5), (1439, 30.0)))

    def test_errors(self):
        for text, key in (
            ("", "schedule_format"),
            ("21,06:00", "schedule_format"),  # even number of values
            ("21,,06:00,18", "schedule_format"),
            ("abc", "schedule_temperature_invalid"),
            ("4.5", "schedule_temperature_range"),
            ("31", "schedule_temperature_range"),
            ("20.3", "schedule_temperature_step"),
            ("21,6,18", "schedule_time_invalid"),
            ("21,24:00,18", "schedule_time_invalid"),
            ("21,06:60,18", "schedule_time_invalid"),
            ("21,00:00,18", "schedule_time_order"),
            ("21,08:00,18,07:00,21", "schedule_time_order"),
            ("21,08:00,18,08:00,21", "schedule_time_order"),
        ):
            with self.assertRaises(schedule.ScheduleError, msg=text) as ctx:
                schedule.parse_day(text)
            self.assertEqual(ctx.exception.key, key, text)


class EntryBytesTest(unittest.TestCase):
    def test_entries_written_by_the_app(self):
        # "Mi 06:07 -> 5 °C" and "Mo-So 18:00 -> 19.5 °C"
        self.assertEqual(encode(Entry(367, WEDNESDAY, 5.0)), "060784200100000101f4")
        self.assertEqual(encode(Entry(1080, ALL_DAYS, 19.5)), "1200ff2001000001079e")
        # Deactivated: bit 7 cleared
        self.assertEqual(encode(Entry(360, WEDNESDAY, 5.0, False)), "060004200100000101f4")

    def test_decode_entries_read_from_the_device(self):
        self.assertEqual(
            decode("051e9f200100000107d0"), Entry(330, WORKDAYS, 20.0, True)
        )
        self.assertEqual(
            decode("0700e020010000010c1a"), Entry(420, SATURDAY | SUNDAY, 21.0, True)
        )
        self.assertEqual(decode("000060200100000103e8"), Entry(0, SATURDAY | SUNDAY, 10.0, False))

    def test_decode_rejects_garbage(self):
        self.assertIsNone(decode("051e9f2001000001"))  # too short
        self.assertIsNone(decode("181e9f200100000107d0"))  # hour 24
        self.assertIsNone(decode("051e9f20010000017fff"))  # invalid temperature


class WeekConversionTest(unittest.TestCase):
    def week(self, *texts):
        if len(texts) == 1:
            texts = texts * 7
        return [schedule.parse_day(text) for text in texts]

    def round_trip(self, week):
        return schedule.entries_to_week(schedule.week_to_entries(week))

    def test_same_days_need_no_midnight_points(self):
        week = self.week("5,06:00,21,18:00,5")
        entries = schedule.week_to_entries(week)
        self.assertEqual(len(entries), 14)
        self.assertNotIn(0, [entry.minute for entry in entries])
        # One day per entry, never merged
        self.assertEqual(sorted(entry.days for entry in entries), sorted([1 << d for d in range(7)] * 2))
        self.assertEqual(self.round_trip(week), week)

    def test_midnight_point_only_where_the_day_starts_differently(self):
        week = self.week(
            "18,06:00,21,22:00,18",
            "18,06:00,21,22:00,18",
            "18,06:00,21,22:00,18",
            "18,06:00,21,22:00,18",
            "18,06:00,21,22:00,18",
            "5,07:00,21",  # Saturday starts with 5, Friday ends with 18
            "21,22:00,18",  # Sunday starts with what Saturday ends with
        )
        entries = schedule.week_to_entries(week)
        midnight = [entry for entry in entries if entry.minute == 0]
        self.assertEqual(midnight, [Entry(0, SATURDAY, 5.0)])
        self.assertEqual(self.round_trip(week), week)

    def test_constant_week_still_writes_one_point(self):
        week = self.week("21")
        self.assertEqual(schedule.week_to_entries(week), [Entry(0, MONDAY, 21.0)])
        self.assertEqual(self.round_trip(week), week)

    def test_inactive_flag(self):
        entries = schedule.week_to_entries(self.week("5,06:00,21"), active=False)
        self.assertFalse(any(entry.active for entry in entries))

    def test_too_many_switch_points(self):
        # 5 switch points per day, every day starts with what it ends with: 35
        busy = "21,05:00,18,08:00,21,12:00,18,14:00,21,17:00,21"
        self.assertEqual(len(schedule.week_to_entries(self.week(busy))), 35)
        # Starting every day with 18 adds a point at 00:00 per day: 42
        with self.assertRaises(schedule.ScheduleError) as ctx:
            schedule.week_to_entries(self.week("18" + busy[2:]))
        self.assertEqual(ctx.exception.key, "schedule_too_many")
        self.assertEqual(ctx.exception.placeholders, {"count": "42", "max": "40"})

    def test_list_of_the_gira_app_in_extended_mode(self):
        # 6 entries read at 10:27 (log 2): 05:30 Mo-Fr, all others Mo-So
        raw = [
            "051e9f200100000107d0",
            "071eff200100000104b0",
            "0b1eff200100000107d0",
            "0d00ff200100000104b0",
            "111eff20010000010c1a",
            "1400ff200100000104b0",
        ]
        week = schedule.entries_to_week([decode(r) for r in raw])
        texts = [schedule.format_day(day) for day in week]
        self.assertEqual(texts[0], "12,05:30,20,07:30,12,11:30,20,13:00,12,17:30,21,20:00,12")
        self.assertEqual(texts[5], "12,07:30,12,11:30,20,13:00,12,17:30,21,20:00,12")

    def test_no_entries(self):
        self.assertIsNone(schedule.entries_to_week([]))


class ScheduleCommandTest(unittest.TestCase):
    def test_frames(self):
        self.assertEqual(
            gira_ble.read_frame(gira_ble.OBJ_SCHEDULE, gira_ble.PID_SCHEDULE_ENTRIES, 0).hex(),
            "fc03f4019c1000",
        )
        self.assertEqual(
            gira_ble.read_frame(gira_ble.OBJ_SCHEDULE, gira_ble.PID_SCHEDULE_ENTRIES, 12).hex(),
            "fc03f4019c100c",
        )
        # The existing setpoint command is a property write as well
        self.assertEqual(
            gira_ble.write_frame(0x0065, 0xF5, 1, b"\x0c\x1a"),
            gira_ble.generate_setpoint_command(21.0),
        )

    def test_clock(self):
        # Written by the app on Sunday 2026-11-15 09:45:34
        self.assertEqual(
            gira_ble.generate_clock_command(datetime(2026, 11, 15, 9, 45, 34)).hex(),
            "f603e901ff10017e0b0fe92d220000",
        )

    def test_write_sequence_as_the_app_does_it(self):
        entry = bytes.fromhex("060784200100000101f4")
        commands = [c.hex() for c in gira_ble.generate_schedule_write_commands([entry], True)]
        self.assertEqual(
            commands,
            [
                "f6018601a5100101",  # extended mode
                "f603f4019c10000000",  # delete all
                "f603f4019c1001060784200100000101f4",
                "f6c35a01051001020000000000000000",
            ],
        )
        commands = gira_ble.generate_schedule_write_commands([], False)
        self.assertEqual(commands[0].hex(), "f603f4019c10000000")

    def test_response_key_pairs_request_and_answer(self):
        request = gira_ble.read_frame(gira_ble.OBJ_SCHEDULE, gira_ble.PID_SCHEDULE_ENTRIES, 1)
        answer = bytes.fromhex("fb03f4019c1001051e9f200100000107d0")
        error = bytes.fromhex("fb03f4019c000105")  # 0 elements
        self.assertEqual(gira_ble.response_key(request), gira_ble.response_key(answer))
        self.assertEqual(gira_ble.response_key(request), gira_ble.response_key(error))
        write = bytes.fromhex("f603f4019c100206")
        self.assertEqual(gira_ble.response_key(write), gira_ble.response_key(bytes.fromhex("f503f4019c1002")))
        self.assertNotEqual(gira_ble.response_key(request), gira_ble.response_key(write))


class FakeThermostat:
    """Open GATT connection that answers property requests like the device."""

    is_connected = True

    def __init__(self, ble_client, answers):
        self.ble_client = ble_client
        self.answers = answers  # request hex -> answer hex (None: no answer)
        self.written = []

    async def start_notify(self, _uuid, _callback):
        return None

    async def write_gatt_char(self, _uuid, data, response):
        self.written.append(bytes(data).hex())
        answer = self.answers.get(bytes(data).hex())
        if answer is not None:
            asyncio.get_running_loop().call_soon(
                self.ble_client._on_notification, None, bytearray.fromhex(answer)
            )


class ExchangeTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.ble = gira_ble.GiraBLEClient(None, "AA:BB:CC:DD:EE:FF", "Test", thermostat=True)

    def connect(self, answers):
        fake = FakeThermostat(self.ble, answers)
        self.ble._client = fake
        return fake

    async def test_read_schedule(self):
        self.connect(
            {
                "fc018601a51001": "fb018601a5100101",
                "fc03f4019c1000": "fb03f4019c10000002",
                "fc03f4019c1001": "fb03f4019c1001060784200100000101f4",
                "fc03f4019c1002": "fb03f4019c10021200ff2001000001079e",
            }
        )
        extended, entries = await self.ble.async_read_schedule()
        self.assertTrue(extended)
        self.assertEqual(
            [e.hex() for e in entries], ["060784200100000101f4", "1200ff2001000001079e"]
        )
        self.assertEqual(self.ble._pending, {})

    async def test_refused_request_raises(self):
        self.connect({"fc03f4019c1005": "fb03f4019c000505"})
        with self.assertRaises(_stubs.HomeAssistantError) as ctx:
            await self.ble.async_exchange(
                [gira_ble.read_frame(gira_ble.OBJ_SCHEDULE, gira_ble.PID_SCHEDULE_ENTRIES, 5)],
                confirm=True,
            )
        self.assertEqual(ctx.exception.translation_key, "property_error")

    async def test_write_waits_for_each_confirmation(self):
        fake = self.connect(
            {
                "fc018601a51001": "fb018601a5100100",  # standard mode
                "f603e901ff10017e0b0fe92d220000": "f503e901ff1001",
                "f6018601a5100101": "f5018601a51001",
                "f603f4019c10000000": "f503f4019c1000",
                "f603f4019c1001060784200100000101f4": "f503f4019c1001",
                "f6c35a01051001020000000000000000": "f5c35a01051001",
            }
        )
        await self.ble.async_write_schedule(
            [bytes.fromhex("060784200100000101f4")], datetime(2026, 11, 15, 9, 45, 34)
        )
        self.assertEqual(len(fake.written), 6)
        self.assertEqual(fake.written[2], "f6018601a5100101")

    def test_exchange_with_confirm_needs_the_thermostat(self):
        cover = gira_ble.GiraBLEClient(None, "AA:BB:CC:DD:EE:FF", "Cover")
        with self.assertRaises(ValueError):
            asyncio.run(cover.async_exchange([bytearray(b"\xfc")], confirm=True))


if __name__ == "__main__":
    unittest.main()
