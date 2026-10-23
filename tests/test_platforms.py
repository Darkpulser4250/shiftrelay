import copy
import gzip
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
import zlib
from unittest.mock import patch

from mitmproxy.test import tflow
from shiftrelay import platforms, policy
from shiftrelay.proxy import ShiftRelay


def youtube():
    return {'playabilityStatus': {'status': 'OK'}, 'videoDetails': {'videoId': 'owned-video'},
            'streamingData': {'adaptiveFormats': [{'url': 'https://media.example.test/content', 'itag': 140}],
                              'licenseInfos': [{'licenseUrl': 'https://license.example.test/untouched'}]},
            'captions': {'tracks': ['untouched']}, 'adPlacements': [{'slot': 'pre'}],
            'playerAds': [{'renderer': 'ad'}], 'adSlots': [{'slot': 'mid'}]}


def instagram():
    return {'status': 'ok', 'num_results': 3, 'more_available': True, 'next_max_id': 'keep-cursor',
            'feed_items': [{'media_or_ad': {'id': 'organic', 'caption': 'sponsored', 'is_paid_partnership': True}},
                           {'media_or_ad': {'id': 'ad', 'ad_id': '123', 'ad_action': 'learn_more'}},
                           {'stories_netego': {'id': 'keep-story'}}]}


def emitted(value):
    return value if isinstance(value, bytes) else b''.join(value)


class PlatformTests(unittest.TestCase):
    def test_youtube_only_prunes_known_ad_metadata_preserves_media_and_drm(self):
        source = youtube()
        result = platforms.transform('youtube_player', json.dumps(source).encode())
        edited = json.loads(result.body)
        self.assertEqual(result.units, 3)
        for key in ('streamingData', 'captions', 'videoDetails', 'playabilityStatus'):
            self.assertEqual(edited[key], source[key])
        self.assertTrue(all(key not in edited for key in ('adPlacements', 'adSlots', 'playerAds')))

    def test_instagram_requires_ad_identity_and_independent_signal(self):
        source = instagram()
        source['feed_items'].extend([{'media_or_ad': {'ad_id': '999', 'id': 'keep-without-signal'}},
                                     {'media_or_ad': {'ad_action': 'learn_more', 'id': 'keep-without-id'}}])
        result = platforms.transform('instagram_timeline', json.dumps(source).encode())
        edited = json.loads(result.body)
        self.assertEqual(result.units, 1)
        self.assertEqual(len(edited['feed_items']), 4)
        self.assertEqual(edited['feed_items'][0], source['feed_items'][0])
        self.assertEqual(edited['next_max_id'], 'keep-cursor')
        self.assertTrue(edited['more_available'])
        # An ambiguous count is left alone.
        self.assertEqual(edited['num_results'], 3)

    def test_instagram_adjusts_only_exact_returned_item_count(self):
        result = platforms.transform('instagram_timeline', json.dumps(instagram()).encode())
        self.assertEqual(json.loads(result.body)['num_results'], 2)

    def test_facebook_json_lines_preserve_organic_nodes_cursors_and_prefix(self):
        first = {'data': {'viewer': {'news_feed': {'edges': [
            {'cursor': 'keep1', 'node': {'id': 'organic', 'text': 'Sponsored content about advertising'}},
            {'cursor': 'keep2', 'category': 'SPONSORED', 'node': {'id': 'ad1'}},
            {'cursor': 'keep3', 'node': {'id': 'ad2', 'metadata': {'__typename': 'SponsoredData'}}}],
            'page_info': {'end_cursor': 'keep3', 'has_next_page': True}}}}}
        second = b'{"extensions": {"keep": true}}\r\n'
        raw = b'for (;;);' + json.dumps(first).encode() + b'\r\n' + second
        result = platforms.transform('facebook_graphql', raw)
        self.assertEqual(result.units, 2)
        self.assertTrue(result.body.startswith(b'for (;;);'))
        self.assertTrue(result.body.endswith(second))
        edited = json.loads(result.body[9:].splitlines()[0])
        feed = edited['data']['viewer']['news_feed']
        self.assertEqual(feed['edges'][0], first['data']['viewer']['news_feed']['edges'][0])
        self.assertEqual(feed['edges'][1]['cursor'], 'keep2')
        self.assertNotIn('node', feed['edges'][1])
        self.assertNotIn('node', feed['edges'][2])
        self.assertEqual(feed['page_info']['end_cursor'], 'keep3')

    def test_malformed_duplicate_deep_or_unknown_json_is_unchanged(self):
        cases = [b'{"data":', b'{"data":{},"data":{}}', b'{"value":NaN}', b'{"value":1e999}', b'[]',
                 b'{"feed_items":[],"status":"challenge_required"}',
                 ('[' * 80 + '0' + ']' * 80).encode()]
        for name in platforms.ADAPTERS:
            for raw in cases:
                with self.subTest(name=name, raw=raw[:40]):
                    result = platforms.transform(name, raw)
                    self.assertEqual(result.body, raw)
                    self.assertEqual(result.units, 0)
        raw = json.dumps({'data': {'category': 'SPONSORED', 'node': {'id': 'ad'}}}).encode() + b'\nnot-json\n'
        self.assertEqual(platforms.transform('facebook_graphql', raw).body, raw)

    def test_youtube_unplayable_or_changed_ad_shape_is_unchanged(self):
        for patch_value in ({'playabilityStatus': {'status': 'LOGIN_REQUIRED'}}, {'adSlots': 'new-schema'},
                            {'streamingData': {}}, {'videoDetails': {}}):
            source = youtube(); source.update(patch_value)
            raw = json.dumps(source).encode()
            self.assertEqual(platforms.transform('youtube_player', raw).body, raw)

    def test_selection_requires_adapter_exact_host_path_method_and_scope(self):
        config = dict(schema=1, version=1, mode='filter', inspect_hosts=['youtubei.googleapis.com'],
                      bypass_hosts=[], block_rules=[], owned_hls_hosts=[], response_adapters=['youtube_player'])
        policy.validate(config)
        self.assertEqual(platforms.select(config, 'youtubei.googleapis.com', '/youtubei/v1/player?key=private', 'POST'), 'youtube_player')
        for host, path, method in [('youtubei.googleapis.com.evil', '/youtubei/v1/player', 'POST'),
                                   ('youtubei.googleapis.com', '/youtubei/v1/player/extra', 'POST'),
                                   ('youtubei.googleapis.com', '/youtubei/v1/player', 'DELETE')]:
            self.assertIsNone(platforms.select(config, host, path, method))
        for patch_value in ({'mode': 'bypass'}, {'bypass_hosts': ['youtubei.googleapis.com']},
                            {'response_adapters': []}, {'inspect_hosts': []}):
            variant = {**config, **patch_value}
            self.assertIsNone(platforms.select(variant, 'youtubei.googleapis.com', '/youtubei/v1/player', 'POST'))
        for adapters in (['netflix_fake'], ['youtube_player', 'youtube_player'], 'youtube_player'):
            with self.assertRaises(ValueError):
                policy.validate({**config, 'response_adapters': adapters})

    def test_bounded_stream_split_chunks_observe_filter_and_policy_change(self):
        raw = json.dumps(youtube()).encode()
        for observe, allowed in ((True, True), (False, True), (False, False)):
            reports = []
            stream = platforms.BoundedResponse('youtube_player', observe, lambda *x: reports.append(x),
                                               can_modify=lambda: allowed)
            output = b''.join(emitted(stream(raw[i:i+7])) for i in range(0, len(raw), 7)) + emitted(stream(b''))
            self.assertEqual(reports[0][0], 3)
            self.assertEqual(output == raw, observe or not allowed)
            self.assertEqual(reports[0][2], not observe and allowed)

    def test_gzip_deflate_and_decompression_bomb_are_bounded(self):
        raw = json.dumps(youtube()).encode()
        for encoding, compress, decompress in [('gzip', gzip.compress, gzip.decompress),
                                                ('deflate', zlib.compress, zlib.decompress)]:
            reports = []
            stream = platforms.BoundedResponse('youtube_player', False, lambda *x: reports.append(x), encoding)
            self.assertEqual(stream(compress(raw)), [])
            output = decompress(stream(b''))
            self.assertNotIn('adSlots', json.loads(output))
            self.assertEqual(reports, [(3, 'matched', True)])
        for source in (gzip.compress(b'x' * (platforms.MAX_BODY + 1)), gzip.compress(raw)[:-3], gzip.compress(raw) + gzip.compress(raw)):
            reports = []
            stream = platforms.BoundedResponse('youtube_player', False, lambda *x: reports.append(x), 'gzip')
            self.assertEqual(emitted(stream(source)) + emitted(stream(b'')), source)
            self.assertEqual(reports, [(0, 'unknown_schema', False)])

    def test_stream_overflow_flushes_original_and_cancellation_discards_buffer(self):
        reports = []
        stream = platforms.BoundedResponse('youtube_player', False, lambda *x: reports.append(x))
        with patch.object(platforms, 'MAX_BODY', 10):
            self.assertEqual(stream(b'12345'), [])
            self.assertEqual(stream(b'678901'), b'12345678901')
            self.assertEqual(stream(b'end'), b'end')
        self.assertEqual(reports, [(0, 'oversize', False)])
        stream = platforms.BoundedResponse('youtube_player', False, lambda *x: None)
        stream(b'private'); stream.cancel()
        self.assertEqual(stream.parts, [])

    def test_proxy_budget_error_cleanup_and_protobuf_passthrough(self):
        proxy = ShiftRelay()
        proxy.current = dict(mode='filter', inspect_hosts=['youtubei.googleapis.com'], bypass_hosts=[],
                             response_adapters=['youtube_player'], owned_hls_hosts=[])
        proxy.write_metrics = lambda **_: None
        flows = []
        for _ in range(5):
            flow = tflow.tflow(resp=True)
            flow.request.host = 'youtubei.googleapis.com'; flow.request.path = '/youtubei/v1/player'
            flow.response.status_code = 200; flow.response.headers['content-type'] = 'application/json'
            flow.response.headers['content-length'] = '100'
            flow.response.headers['etag'] = 'old'
            proxy.responseheaders(flow); flows.append(flow)
        self.assertEqual(len(proxy.buffers), 4)
        self.assertIs(flows[-1].response.stream, True)
        self.assertEqual(proxy.platform_counts['youtube_player']['buffer_budget'], 1)
        self.assertNotIn('content-length', flows[0].response.headers)
        self.assertNotIn('etag', flows[0].response.headers)
        proxy.error(flows[0]); self.assertEqual(len(proxy.buffers), 3)
        flow = flows[-1]; flow.response.headers['content-type'] = 'application/x-protobuf'
        proxy.responseheaders(flow)
        self.assertIs(flow.response.stream, True)
        self.assertEqual(proxy.platform_counts['youtube_player']['binary_unhandled'], 1)

    def test_profile_cli_expands_only_explicit_platforms_preserves_bypasses_and_backups(self):
        root = Path(__file__).resolve().parents[1]
        source = (root / 'config/android.policy.json').read_bytes()
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / 'policy.json'; path.write_bytes(source)
            command = [sys.executable, str(root / 'scripts/enable_platform.py'), '--policy', str(path),
                       '--platform', 'instagram', '--mode', 'observe']
            preview = subprocess.check_output([*command, '--dry-run'], text=True)
            self.assertEqual(path.read_bytes(), source)
            config = json.loads(preview)
            self.assertEqual(config['response_adapters'], ['instagram_timeline'])
            self.assertIn('i.instagram.com', config['inspect_hosts'])
            self.assertNotIn('youtubei.googleapis.com', config['inspect_hosts'])
            subprocess.check_output(command)
            self.assertEqual(json.loads(path.read_text()), config)
            self.assertEqual(path.with_suffix('.previous.json').read_bytes(), source)
            config['bypass_hosts'] = ['i.instagram.com']; path.write_text(json.dumps(config))
            subprocess.check_output(command)
            self.assertEqual(json.loads(path.read_text())['bypass_hosts'], ['i.instagram.com'])


if __name__ == '__main__':
    unittest.main()
