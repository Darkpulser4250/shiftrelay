# SPDX-License-Identifier: GPL-3.0-only
import asyncio
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from aiohttp import web
from pyytlounge import AdStateEvent, State
from ytbridge.cli import load_auth, pair, session
from ytbridge.controller import Controller
from ytbridge.protocol import Listener, Transport, make_api


def frame(events):
    text = json.dumps(events)
    return str(len(text)+1) + '\n' + text + '\n'


class ProtocolTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.state = Path(self.temp.name)
        self.commands = []
        app = web.Application()
        app.router.add_post('/pairing/get_screen', self.pairing)
        app.router.add_post('/pairing/get_lounge_token_batch', self.refresh)
        app.router.add_post('/bc/bind', self.bind)
        app.router.add_get('/bc/bind', self.subscribe)
        self.runner = web.AppRunner(app); await self.runner.setup()
        self.site = web.TCPSite(self.runner, '127.0.0.1', 0); await self.site.start()
        port = self.site._server.sockets[0].getsockname()[1]
        self.patch = patch('pyytlounge.wrapper.api_base', f'http://127.0.0.1:{port}')
        self.patch.start()

    async def asyncTearDown(self):
        self.patch.stop(); await self.runner.cleanup(); self.temp.cleanup()

    async def pairing(self, request):
        self.assertEqual((await request.post())['pairing_code'], '123456789012')
        return web.json_response({'screen': {'name': 'private-screen-name', 'screenId': 'lab-screen', 'loungeToken': 'private-token'}})

    async def refresh(self, request):
        self.assertEqual((await request.post())['screen_ids'], 'lab-screen')
        return web.json_response({'screens': [{'screenId': 'lab-screen', 'loungeToken': 'refreshed-private-token'}]})

    async def bind(self, request):
        data = await request.post()
        if 'req0__sc' in data:
            self.commands.append(dict(data))
            return web.Response(text='ok')
        if data.get('TYPE') == 'terminate':
            return web.Response(text='ok')
        return web.Response(text=frame([[0, ['c', 'session']], [1, ['S', 'gsession']],
            [2, ['onVolumeChanged', {'volume': '42', 'muted': 'false'}]],
            [3, ['nowPlaying', {'videoId': 'private-video', 'state': '1', 'currentTime': '8', 'duration': '200'}]]]))

    async def subscribe(self, request):
        return web.Response(text=frame([
            [4, ['onAdStateChange', {'adState': '1', 'currentTime': '1', 'isSkipEnabled': 'true'}]],
            [5, ['onVolumeChanged', {'volume': '0', 'muted': 'false'}]],
            [6, ['onStateChange', {'state': '1', 'currentTime': '8', 'duration': '200'}]],
        ]))

    async def test_actual_library_pair_auth_roundtrip_and_native_commands(self):
        await pair(self.state, read_code=lambda _: '123 456 789 012')
        saved = load_auth(self.state/'auth.json')
        self.assertEqual(saved['version'], 0)
        self.assertEqual((self.state/'auth.json').stat().st_mode & 0o777, 0o600)
        listener = Listener()
        async with make_api(listener) as api:
            api.load_auth_state(saved)
            self.assertTrue(await api.refresh_auth())
            controller = Controller(Transport(api), self.state, 'fixture-screen', mode='assist', allow_skip=True)
            listener.controller = controller
            self.assertTrue(await api.connect())
            await controller.connection(True)
            await asyncio.wait_for(api.subscribe(), 3)
            actions = [(c['req0__sc'], c.get('req0_volume')) for c in self.commands]
            self.assertEqual(actions, [('skipAd', None), ('setVolume', '0'), ('setVolume', '42')])
            status = json.dumps(controller.snapshot())
            for private in ['private-video', 'private-screen-name', 'private-token', 'lab-screen']:
                self.assertNotIn(private, status)
            await controller.connection(False)
            self.assertTrue(await api.disconnect())

    async def test_unknown_enum_abstains_and_restores(self):
        class Fake:
            def __init__(self): self.calls=[]
            async def set_volume(self, v): self.calls.append(v); return True
        device=Fake(); controller=Controller(device, self.state, 'lab', mode='assist')
        await controller.volume_changed(42, False); await controller.connection(True)
        await controller.ad(True)
        listener=Listener(); listener.controller=controller
        await listener.ad_state_changed(AdStateEvent({'adState':'999999', 'currentTime':'1', 'isSkipEnabled':'true'}))
        self.assertEqual(device.calls, [0, 42]); self.assertIsNone(controller.ad_active)

    async def test_pairing_refuses_unintentional_replacement(self):
        await pair(self.state, read_code=lambda _: '123456789012')
        with self.assertRaises(ValueError): await pair(self.state, read_code=lambda _: '123456789012')

    async def test_full_runtime_with_actual_library_and_local_service(self):
        await pair(self.state, read_code=lambda _: '123456789012')
        status_path = self.state/'public/youtube-tv.json'
        await asyncio.wait_for(session(self.state, status_path, 'assist', True, asyncio.Event()), 4)
        status = json.loads(status_path.read_text())
        self.assertFalse(status['connected'])
        self.assertEqual(status['counters']['skip_requests'], 1)
        self.assertEqual(status['counters']['lower_requests'], 1)
        self.assertNotIn('private-token', status_path.read_text())


if __name__ == '__main__': unittest.main()
