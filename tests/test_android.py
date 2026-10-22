import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from mitmproxy import dns
from mitmproxy.test import tflow
from shiftrelay.android import client_config, endpoint, ensure_keys, read_keys
from shiftrelay.android_proxy import AndroidLab


class AndroidConfigTests(unittest.TestCase):
    def test_peer_keys_persist_and_are_private(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / 'wireguard.conf'
            keys = ensure_keys(path)
            self.assertEqual(keys, ensure_keys(path))
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            path.chmod(0o644)
            with self.assertRaises(ValueError):
                read_keys(path)

    def test_endpoint_rejects_configuration_injection(self):
        for remote in ('192.168.1.10:51820', 'my-pi.local:51820', '[fd00::1]:51820'):
            self.assertEqual(endpoint(remote), remote)
        for remote in ('host:0', 'host:65536', 'host:abc', 'host:12\nPrivateKey=x', 'https://host:12', 'host', '[:::]:12'):
            with self.subTest(remote=remote), self.assertRaises(ValueError):
                endpoint(remote)

    def test_config_is_per_app_and_includes_both_ip_families(self):
        with tempfile.TemporaryDirectory() as temporary:
            keys = ensure_keys(Path(temporary) / 'wireguard.conf')
            config = client_config(keys, '192.168.1.10:51820', ['youtube', 'youtube'])
        self.assertIn('AllowedIPs = 0.0.0.0/0, ::/0', config)
        self.assertIn('IncludedApplications = org.shiftrelay.probe, com.google.android.youtube\n', config)
        self.assertNotIn(keys['server_key'], config)
        self.assertNotIn('com.netflix.mediaclient', config)
        with self.assertRaises(ValueError):
            client_config(keys, 'host:51820', ['unknown'])


class AndroidLabTests(unittest.TestCase):
    def test_virtual_origin_does_not_replace_external_hosts(self):
        lab = AndroidLab()
        flow = tflow.tflow()
        flow.request.host = 'youtube.com'
        lab.requestheaders(flow)
        self.assertIsNone(flow.response)
        flow.request.host = 'relay-test.invalid'
        flow.request.path = '/content?not-recorded=secret'
        lab.requestheaders(flow)
        self.assertEqual(flow.response.status_code, 200)
        self.assertTrue(json.loads(flow.response.content)['preserved'])
        self.assertNotIn('secret', json.dumps(lab.counts))

    def test_core_block_response_is_preserved(self):
        flow = tflow.tflow(resp=True)
        original = flow.response
        flow.request.host = 'relay-test.invalid'
        AndroidLab().requestheaders(flow)
        self.assertIs(flow.response, original)

    def test_lab_dns_only_and_no_synthetic_ipv6(self):
        lab = AndroidLab()
        flow = tflow.tdnsflow()
        flow.request.questions = [dns.Question('relay-test.invalid', dns.types.A, dns.classes.IN)]
        lab.dns_request(flow)
        self.assertEqual(str(flow.response.answers[0].ipv4_address), '10.0.0.2')
        flow.response = None
        flow.request.questions[0].type = dns.types.AAAA
        lab.dns_request(flow)
        self.assertEqual(flow.response.answers, [])
        flow.response = None
        flow.request.questions[0].name = 'youtube.com'
        lab.dns_request(flow)
        self.assertIsNone(flow.response)

    def test_status_contains_no_hosts_queries_or_tokens(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / 'android.json'
            with patch.dict(os.environ, {'SHIFTRELAY_ANDROID_STATUS': str(path)}):
                lab = AndroidLab()
            lab.write()
            value = json.loads(path.read_text())
        self.assertEqual(value['platform_ad_removal'], 'unvalidated')
        self.assertEqual(set(value), {'schema', 'transport', 'started_at', 'updated_at', 'counters', 'platform_ad_removal'})

    def test_dns_discovery_requires_opt_in_and_is_bounded(self):
        flow = tflow.tdnsflow()
        flow.request.questions = [dns.Question('a.example.org', dns.types.A, dns.classes.IN)]
        lab = AndroidLab(); lab.dns_request(flow)
        self.assertEqual(lab.destinations, {})
        with tempfile.TemporaryDirectory() as temporary:
            with patch.dict(os.environ, {'SHIFTRELAY_CA': temporary, 'SHIFTRELAY_ANDROID_STATUS': temporary + '/status.json',
                                         'SHIFTRELAY_ANDROID_DISCOVERY': 'true'}):
                lab = AndroidLab()
            for i in range(140):
                flow.request.questions[0].name = f'h{i}.example.org'
                lab.dns_request(flow)
            lab.write()
            self.assertEqual(len(lab.destinations), 128)
            self.assertEqual(lab.discovery_path.stat().st_mode & 0o777, 0o600)
            self.assertNotIn('example.org', (Path(temporary) / 'status.json').read_text())


if __name__ == '__main__':
    unittest.main()
