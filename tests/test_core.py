import copy
import json
from pathlib import Path
import tempfile
import unittest
from shiftrelay.policy import decide, load, tls_allow_hosts, validate
from shiftrelay.hls import rewrite

ROOT = Path(__file__).resolve().parents[1]


class PolicyTests(unittest.TestCase):
    def setUp(self):
        self.policy = load(ROOT / 'fixtures/policy.demo.json')

    def test_exact_host_path_only(self):
        self.assertEqual(decide(self.policy, 'localhost', '/ads.js?token=secret', 'GET')['action'], 'block')
        for host, path, method in [('localhost.evil', '/ads.js', 'GET'), ('localhost', '/ads.js2', 'GET'), ('localhost', '/ads.js', 'POST')]:
            self.assertEqual(decide(self.policy, host, path, method)['action'], 'pass')

    def test_default_never_inspects_tls(self):
        p = load(ROOT / 'config/policy.json')
        self.assertEqual(tls_allow_hosts(p), ['(?!)'])
        self.assertEqual(decide(p, 'netflix.com', '/anything', 'GET')['action'], 'pass')

    def test_bypass_precedence(self):
        self.policy['bypass_hosts'] = ['localhost']
        self.assertEqual(tls_allow_hosts(self.policy), ['(?!)'])
        self.assertEqual(decide(self.policy, 'localhost', '/ads.js', 'GET')['action'], 'pass')

    def test_observe_never_blocks(self):
        self.policy['mode'] = 'observe'
        self.assertEqual(decide(self.policy, 'localhost', '/ads.js', 'GET')['action'], 'observe')

    def test_unsafe_policy_rejected(self):
        for patch in [{'inspect_hosts': ['*.com']}, {'mode': 'execute'}, {'version': -1}, {'surprise': True}, {'block_rules': [{'id': 'x', 'host': 'netflix.com', 'path': '/'}]}]:
            p = copy.deepcopy(self.policy); p.update(patch)
            with self.assertRaises(ValueError):
                validate(p)


class HLSTests(unittest.TestCase):
    def setUp(self):
        self.source = (ROOT / 'fixtures/owned-vod.m3u8').read_text()

    def test_only_owned_marked_segments_removed(self):
        result, n = rewrite(self.source)
        self.assertEqual(n, 2)
        self.assertNotIn('ad-000.ts', result)
        self.assertIn('content-000.ts', result)
        self.assertIn('content-001.ts', result)
        self.assertIn('#EXT-X-DISCONTINUITY', result)

    def test_unsafe_manifests_unchanged(self):
        cases = [self.source.replace('#EXT-X-ENDLIST', ''), self.source.replace('#EXT-X-PLAYLIST-TYPE:VOD', '#EXT-X-PLAYLIST-TYPE:EVENT'),
                 self.source.replace('#EXT-X-VERSION:3', '#EXT-X-KEY:METHOD=AES-128,URI="key"'),
                 self.source.replace('#EXT-X-VERSION:3', '#EXT-X-MAP:URI="init.mp4"'),
                 self.source.replace('#EXT-X-SHIFTRELAY-AD-END', ''), self.source.replace('#EXTINF:6.0,', '#EXTINF:nan,')]
        for text in cases:
            self.assertEqual(rewrite(text), (text, 0))

    def test_duplicate_end_marker_unchanged(self):
        text = self.source.replace('#EXT-X-VERSION:3', '#EXT-X-ENDLIST\n#EXT-X-VERSION:3')
        self.assertEqual(rewrite(text), (text, 0))


if __name__ == '__main__':
    unittest.main()
