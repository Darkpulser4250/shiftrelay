# SPDX-License-Identifier: GPL-3.0-only
import asyncio
import json
from pathlib import Path
import tempfile
import unittest
from ytbridge.controller import Controller
from ytbridge.storage import atomic_json


class Clock:
    now = 100.0
    def monotonic(self): return self.now
    def wall(self): return self.now + 1000


class Device:
    def __init__(self): self.calls = []; self.fail = False; self.delay = 0
    async def set_volume(self, value):
        self.calls.append(('volume', value))
        await asyncio.sleep(self.delay)
        return not self.fail
    async def skip_ad(self):
        self.calls.append(('skip',))
        return not self.fail


class ControllerTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.state = Path(self.temp.name)
        self.device = Device(); self.clock = Clock()

    def tearDown(self): self.temp.cleanup()

    def build(self, mode='assist', skip=False, **kwargs):
        return Controller(self.device, self.state, 'same-screen', mode=mode, allow_skip=skip,
                          clock=self.clock.monotonic, wall=self.clock.wall, **kwargs)

    async def ready(self, controller, volume=42, muted=False):
        await controller.volume_changed(volume, muted)
        await controller.connection(True)

    async def test_observe_never_sends_playback_commands(self):
        controller = self.build(mode='observe', skip=True)
        await self.ready(controller)
        await controller.ad(True, True); await controller.ad(False)
        self.assertEqual(self.device.calls, [])

    async def test_lower_then_restore_only_our_volume(self):
        controller = self.build(); await self.ready(controller)
        await controller.ad(True); await controller.volume_changed(0, False)
        self.assertTrue((self.state/'restore.json').is_file())
        await controller.ad(False)
        self.assertEqual(self.device.calls, [('volume', 0), ('volume', 42)])
        self.assertTrue(controller.snapshot()['pending_restore'])
        await controller.volume_changed(42, False)
        self.assertFalse((self.state/'restore.json').exists())

    async def test_unknown_volume_does_not_guess_restore_value(self):
        controller = self.build(); await controller.connection(True); await controller.ad(True)
        self.assertEqual(self.device.calls, [])

    async def test_preexisting_mute_or_zero_preserved(self):
        for volume, muted in [(42, True), (0, False), (0, True)]:
            controller = self.build(); await self.ready(controller, volume, muted)
            await controller.ad(True); await controller.ad(False)
        self.assertEqual(self.device.calls, [])

    async def test_manual_change_during_ad_is_respected(self):
        controller = self.build(); await self.ready(controller); await controller.ad(True)
        await controller.volume_changed(17, False)
        await controller.ad(True); await controller.ad(False)
        self.assertEqual(self.device.calls, [('volume', 0)])
        self.assertFalse(controller.snapshot()['pending_restore'])

    async def test_sixty_second_budget_does_not_rearm_until_clear(self):
        controller = self.build(); await self.ready(controller); await controller.ad(True)
        self.clock.now += 61; await controller.tick(); await controller.ad(True)
        self.assertEqual(self.device.calls, [('volume', 0), ('volume', 42)])
        await controller.volume_changed(42, False)
        await controller.ad(False); await controller.ad(True)
        self.assertEqual(self.device.calls[-1], ('volume', 0))

    async def test_skip_requires_separate_opt_in_and_enabled_signal(self):
        controller = self.build(skip=False); await self.ready(controller, 0)
        await controller.ad(True, True)
        self.assertEqual(self.device.calls, [])
        controller = self.build(skip=True); await self.ready(controller, 0)
        await controller.ad(True, False); await controller.ad(True, True)
        await controller.ad(True, True)
        self.assertEqual(self.device.calls, [('skip',)])

    async def test_skip_retries_bounded_and_rate_limited(self):
        controller = self.build(skip=True); await self.ready(controller, 0)
        for _ in range(10):
            await controller.ad(True, True); await controller.ad(None); self.clock.now += 6
        self.assertEqual(self.device.calls, [('skip',)]*3)

    async def test_disconnect_restores_before_releasing_connection(self):
        controller = self.build(); await self.ready(controller); await controller.ad(True)
        await controller.connection(False)
        self.assertEqual(self.device.calls, [('volume', 0), ('volume', 42)])
        self.assertFalse(controller.connected)

    async def test_failed_command_keeps_journal_and_reconnect_recovers(self):
        controller = self.build(); await self.ready(controller)
        self.device.fail = True; await controller.ad(True); await controller.connection(False)
        self.assertTrue(controller.snapshot()['pending_restore'])
        self.device.fail = False; self.device.calls.clear()
        recovered = self.build(mode='observe'); await self.ready(recovered, 0)
        self.assertEqual(self.device.calls, [('volume', 42)])
        await recovered.volume_changed(42, False)
        self.assertFalse(recovered.snapshot()['pending_restore'])

    async def test_accepted_restore_without_tv_ack_survives_process_restart(self):
        controller = self.build(); await self.ready(controller); await controller.ad(True)
        await controller.volume_changed(0, False); await controller.ad(False)
        self.assertTrue(controller.snapshot()['pending_restore'])
        self.device.calls.clear()
        recovered = self.build(mode='observe'); await self.ready(recovered, 0)
        self.assertEqual(self.device.calls, [('volume', 42)])
        await recovered.volume_changed(42, False)
        self.assertFalse(recovered.snapshot()['pending_restore'])

    async def test_recovery_does_not_override_a_new_volume(self):
        controller = self.build(); await self.ready(controller); await controller.ad(True)
        recovered = self.build(); self.device.calls.clear(); await self.ready(recovered, 31)
        self.assertEqual(self.device.calls, [])
        self.assertFalse(recovered.snapshot()['pending_restore'])

    async def test_expired_or_other_device_recovery_requires_manual_action(self):
        for fingerprint, created in [('same-screen', -1000), ('other-screen', self.clock.wall())]:
            atomic_json(self.state/'restore.json', dict(volume=42, created_at=created, screen_fingerprint=fingerprint))
            controller = self.build(); await self.ready(controller, 0); await controller.ad(True)
            self.assertTrue(controller.snapshot()['pending_restore'])
        self.assertEqual(self.device.calls, [])

    async def test_unknown_ad_state_restores_and_abstains(self):
        controller = self.build(); await self.ready(controller); await controller.ad(True)
        await controller.ad(None)
        self.assertEqual(self.device.calls[-1], ('volume', 42))
        self.assertIsNone(controller.snapshot()['ad_active'])
        await controller.volume_changed(42, False)
        await controller.ad(True)
        self.assertEqual(self.device.calls, [('volume', 0), ('volume', 42)])
        await controller.ad(False); await controller.ad(True)
        self.assertEqual(self.device.calls[-1], ('volume', 0))

    async def test_timeout_is_bounded_and_recoverable(self):
        controller = self.build(command_timeout=.01); await self.ready(controller)
        self.device.delay = .05
        await controller.ad(True)
        self.assertTrue(controller.snapshot()['pending_restore'])
        self.assertGreaterEqual(controller.snapshot()['counters']['command_failures'], 1)

    async def test_status_never_contains_volume_or_screen_identity(self):
        controller = self.build(); await self.ready(controller); await controller.ad(True)
        text = json.dumps(controller.snapshot())
        self.assertNotIn('same-screen', text)
        self.assertNotIn('"volume":', text)
        self.assertNotIn('auth', text)

    async def test_invalid_volume_rejected(self):
        controller = self.build()
        for volume, muted in [(True, False), (101, False), (20, 'false')]:
            with self.assertRaises(ValueError): await controller.volume_changed(volume, muted)


if __name__ == '__main__': unittest.main()
