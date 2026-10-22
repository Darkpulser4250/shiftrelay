import json
from pathlib import Path
import tempfile
import unittest
from shiftrelay.native_status import read_native_status


class NativeStatusTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.root = Path(self.temp.name)
        self.value = dict(schema=1, adapter='youtube_tv', mode='observe', connected=True,
                          ad_active=None, skip_enabled=False, volume_owned=False, pending_restore=False,
                          manual_override=False, reason='observing', updated_at=1000,
                          counters=dict(ad_breaks=0, lower_requests=0, restore_requests=0, skip_requests=0, command_failures=0))

    def tearDown(self): self.temp.cleanup()

    def write(self): (self.root/'youtube-tv.json').write_text(json.dumps(self.value))

    def test_missing_bridge_is_optional(self):
        self.assertIsNone(read_native_status(self.root, now=1000))

    def test_valid_status(self):
        self.write(); value = read_native_status(self.root, now=1000)
        self.assertTrue(value['connected']); self.assertFalse(value['stale'])

    def test_stale_status_cannot_claim_connected(self):
        self.write(); value = read_native_status(self.root, now=1100)
        self.assertFalse(value['connected']); self.assertTrue(value['stale'])

    def test_unexpected_secret_fields_rejected(self):
        self.value['auth'] = 'never-return-this'; self.write()
        self.assertIsNone(read_native_status(self.root, now=1000))

    def test_malformed_fields_and_unbounded_input_rejected(self):
        for field, replacement in [('updated_at', 99999), ('connected', 'true'), ('counters', []), ('reason', '<script>')]:
            previous = self.value[field]; self.value[field] = replacement; self.write()
            self.assertIsNone(read_native_status(self.root, now=1000)); self.value[field] = previous
        (self.root/'youtube-tv.json').write_text(' '*8193)
        self.assertIsNone(read_native_status(self.root, now=1000))


if __name__ == '__main__': unittest.main()
