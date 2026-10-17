"""Tests for the opening/closing state of the cover."""
import asyncio
import time
import types
import unittest

from tests import _stubs

cover = _stubs.load("cover")
gira_ble = _stubs.load("gira_ble")


class FakeClient:
    address = "AA:BB:CC:DD:EE:FF"
    name = "Test"

    def __init__(self, fail=False):
        self.calls = []
        self.fail = fail

    async def _record(self, call):
        if self.fail:
            raise _stubs.HomeAssistantError("failed")
        self.calls.append(call)

    async def send_up_command(self):
        await self._record("up")

    async def send_down_command(self):
        await self._record("down")

    async def send_stop_command(self):
        await self._record("stop")

    async def set_absolute_position(self, position):
        await self._record(position)


def run(coro):
    return asyncio.run(coro)


class CoverStateTest(unittest.TestCase):
    def setUp(self):
        _stubs.timers.clear()
        self.coordinator = types.SimpleNamespace(data=None)
        self.client = FakeClient()
        self.cover = self.make_cover(self.client)

    def make_cover(self, client):
        entity = cover.GireaSystem3000Cover(self.coordinator, client)
        entity.hass = object()
        entity.async_write_ha_state = lambda: None
        return entity

    def push(self, **values):
        """Simulate a broadcast: set the values with a fresh timestamp."""
        data = dict(self.coordinator.data or {})
        now = time.monotonic() + len(_stubs.timers) * 1e-3
        for key, value in values.items():
            data[key] = value
            data[f"{key}_updated"] = now
        self.coordinator.data = data
        self.cover._handle_coordinator_update()

    def age_movement(self, seconds):
        self.cover._movement_started -= seconds

    def test_close_and_open_set_the_direction_at_once(self):
        run(self.cover.async_close_cover())
        self.assertTrue(self.cover.is_closing)
        self.assertFalse(self.cover.is_opening)
        run(self.cover.async_open_cover())
        self.assertTrue(self.cover.is_opening)
        self.assertFalse(self.cover.is_closing)
        self.assertEqual(self.client.calls, ["down", "up"])

    def test_failed_command_does_not_change_the_state(self):
        failing = self.make_cover(FakeClient(fail=True))
        with self.assertRaises(_stubs.HomeAssistantError):
            run(failing.async_open_cover())
        self.assertFalse(failing.is_opening)

    def test_stop_resets_the_state(self):
        run(self.cover.async_open_cover())
        run(self.cover.async_stop_cover())
        self.assertFalse(self.cover.is_opening)
        self.assertTrue(_stubs.timers[-1][2])  # timer cancelled

    def test_new_command_cancels_the_old_timer(self):
        run(self.cover.async_open_cover())
        first = _stubs.timers[-1]
        run(self.cover.async_close_cover())
        self.assertTrue(first[2])
        self.assertTrue(self.cover.is_closing)

    def test_stale_stopped_status_is_ignored_right_after_a_command(self):
        run(self.cover.async_close_cover())
        self.push(moving=False)
        self.assertTrue(self.cover.is_closing)

    def test_stopped_status_ends_the_movement_later(self):
        run(self.cover.async_close_cover())
        self.age_movement(30)
        self.push(moving=True)
        self.assertTrue(self.cover.is_closing)
        self.push(moving=False)
        self.assertFalse(self.cover.is_closing)

    def test_unknown_position_uses_the_maximum_duration(self):
        run(self.cover.async_open_cover())
        self.assertEqual(_stubs.timers[-1][0], cover.MOVEMENT_TIMEOUT)

    def test_duration_depends_on_the_distance(self):
        self.push(position=50)
        run(self.cover.async_set_cover_position(position=60))
        expected = 10 * cover.SECONDS_PER_PERCENT + cover.MOVEMENT_MARGIN
        self.assertAlmostEqual(_stubs.timers[-1][0], expected)

    def test_estimated_end_assumes_the_target_position(self):
        self.push(position=100)
        run(self.cover.async_close_cover())
        _stubs.timers[-1][1](None)  # the estimated run time is over
        self.assertFalse(self.cover.is_closing)
        self.assertEqual(self.cover.current_cover_position, 0)
        self.assertTrue(self.cover.is_closed)

    def test_old_position_does_not_overwrite_the_estimate(self):
        self.push(position=100)
        run(self.cover.async_close_cover())
        _stubs.timers[-1][1](None)
        # another property arrives; the data still holds the old position
        self.push(moving=False)
        self.assertEqual(self.cover.current_cover_position, 0)

    def test_real_position_corrects_the_estimate(self):
        self.push(position=100)
        run(self.cover.async_close_cover())
        _stubs.timers[-1][1](None)
        self.push(position=37)
        self.assertEqual(self.cover.current_cover_position, 37)

    def test_reaching_the_target_ends_the_movement(self):
        self.push(position=0)
        run(self.cover.async_open_cover())
        self.age_movement(30)
        self.push(position=70)
        self.assertTrue(self.cover.is_opening)
        self.push(position=100)
        self.assertFalse(self.cover.is_opening)

    def test_old_end_position_is_ignored_right_after_a_command(self):
        self.push(position=0)
        run(self.cover.async_close_cover())
        self.push(position=0)
        self.assertTrue(self.cover.is_closing)

    def test_set_position_direction(self):
        self.push(position=50)
        run(self.cover.async_set_cover_position(position=80))
        self.assertTrue(self.cover.is_opening)
        run(self.cover.async_set_cover_position(position=20))
        self.assertTrue(self.cover.is_closing)
        run(self.cover.async_set_cover_position(position=50))
        self.assertFalse(self.cover.is_closing)
        self.assertFalse(self.cover.is_opening)

    def test_set_position_without_known_position_does_not_guess(self):
        run(self.cover.async_set_cover_position(position=50))
        self.assertFalse(self.cover.is_opening)
        self.assertFalse(self.cover.is_closing)


if __name__ == "__main__":
    unittest.main()
