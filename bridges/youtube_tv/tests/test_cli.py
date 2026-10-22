# SPDX-License-Identifier: GPL-3.0-only
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from ytbridge.cli import load_auth, pair, run
from ytbridge.storage import atomic_json, read_json


class CLITests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.root = Path(self.temp.name)

    def tearDown(self): self.temp.cleanup()

    async def test_unpaired_once_is_offline_and_passive(self):
        state = self.root/'state'; status = self.root/'status/youtube-tv.json'
        with patch('ytbridge.cli.session', side_effect=AssertionError('No network session should be attempted')):
            await run(state, status, 'observe', False, once=True)
        value = read_json(status)
        self.assertEqual(value['reason'], 'awaiting_pairing')
        self.assertEqual(value['counters']['lower_requests'], 0)
        self.assertFalse((state/'auth.json').exists())

    async def test_invalid_code_does_not_open_a_session(self):
        with self.assertRaises(ValueError):
            await pair(self.root, api_factory=lambda: self.fail('Network must not be opened'), read_code=lambda _: 'wrong-code')

    async def test_pending_restore_blocks_repairing(self):
        atomic_json(self.root/'restore.json', {'pending': True})
        with self.assertRaises(ValueError):
            await pair(self.root, replace=True, api_factory=lambda: self.fail('Network must not be opened'), read_code=lambda _: '123456789012')

    async def test_world_readable_auth_refused(self):
        path = self.root/'auth.json'; atomic_json(path, {})
        path.chmod(0o644)
        with self.assertRaises(ValueError): load_auth(path)

    async def test_bounded_json_and_atomic_private_permissions(self):
        path = self.root/'auth.json'; atomic_json(path, {'not': 'real credentials'})
        self.assertEqual(path.stat().st_mode & 0o777, 0o600)
        with self.assertRaises(ValueError): read_json(path, limit=2)


if __name__ == '__main__': unittest.main()
