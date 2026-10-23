"""Real mitmdump HTTPS fixture and WireGuard listener lifecycle, no Internet."""
import http.client
import json
import os
from pathlib import Path
import socket
import ssl
import subprocess
import sys
import tempfile
import time
import unittest

ROOT = Path(__file__).resolve().parents[1]


class AndroidIntegration(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.folder = Path(cls.temp.name)
        cls.env = dict(os.environ, PYTHONPATH=str(ROOT), SHIFTRELAY_CA=str(cls.folder / 'ca'),
                       SHIFTRELAY_PUBLIC=str(cls.folder / 'public'),
                       SHIFTRELAY_POLICY=str(ROOT / 'config/android.policy.json'),
                       SHIFTRELAY_ANDROID_STATUS=str(cls.folder / 'android.json'),
                       SHIFTRELAY_METRICS=str(cls.folder / 'metrics.json'))
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.bind(('127.0.0.1', 0)); cls.env['SHIFTRELAY_WG_PORT'] = str(sock.getsockname()[1])
        cls.log = open(cls.folder / 'wg.log', 'w+')
        cls.wg = subprocess.Popen([sys.executable, '-m', 'shiftrelay.android', 'run'], env=cls.env,
                                  cwd=ROOT, stdout=cls.log, stderr=cls.log)
        deadline = time.monotonic() + 12
        while time.monotonic() < deadline:
            if (cls.folder / 'android.json').exists(): break
            if cls.wg.poll() is not None:
                cls.log.seek(0); raise RuntimeError(cls.log.read())
            time.sleep(.1)
        else:
            cls.wg.terminate(); cls.wg.wait(); raise RuntimeError('WireGuard listener startup timed out')
        # Reuse that CA with a second real transport to test the virtual HTTPS
        # fixture locally. Actual WireGuard packets are tested by the CI kernel peer.
        with socket.socket() as sock:
            sock.bind(('127.0.0.1', 0)); cls.port = sock.getsockname()[1]
        cls.http_log = open(cls.folder / 'http.log', 'w+')
        args = [str(Path(sys.executable).with_name('mitmdump')), '--mode', 'regular', '--listen-host', '127.0.0.1',
                '--listen-port', str(cls.port), '--set', 'confdir=' + str(cls.folder / 'ca'),
                '--set', 'flow_detail=0', '--set', 'termlog_verbosity=error',
                '--set', 'connection_strategy=lazy', '--set', 'upstream_cert=false',
                '--allow-hosts', r'^(relay-test|system-test)\.invalid(?::[0-9]+)?$',
                '-s', str(ROOT / 'shiftrelay/android_proxy.py')]
        cls.http = subprocess.Popen(args, cwd=ROOT, env=cls.env, stdout=cls.http_log, stderr=cls.http_log)
        deadline = time.monotonic() + 12
        while time.monotonic() < deadline:
            try:
                with socket.create_connection(('127.0.0.1', cls.port), timeout=.2): return
            except OSError:
                time.sleep(.1)
        cls.http_log.seek(0); message = cls.http_log.read()
        cls.tearDownClass(); raise RuntimeError('Fixture proxy failed to start: ' + message)

    @classmethod
    def tearDownClass(cls):
        for process in (getattr(cls, 'http', None), getattr(cls, 'wg', None)):
            if process:
                process.terminate()
                try: process.wait(timeout=5)
                except subprocess.TimeoutExpired: process.kill(); process.wait()
        for log in (getattr(cls, 'log', None), getattr(cls, 'http_log', None)):
            if log: log.close()
        cls.temp.cleanup()

    def request(self, path, trusted=True):
        ca = str(self.folder / 'public/shiftrelay-ca.crt') if trusted else None
        connection = http.client.HTTPSConnection('127.0.0.1', self.port, context=ssl.create_default_context(cafile=ca), timeout=5)
        connection.set_tunnel('relay-test.invalid', 443)
        try:
            connection.request('GET', path)
            reply = connection.getresponse()
            return reply.status, reply.getheader('X-ShiftRelay'), reply.read()
        finally:
            connection.close()

    def test_owned_content_survives_and_ad_is_blocked(self):
        status, _, body = self.request('/content')
        self.assertEqual(status, 200)
        self.assertTrue(json.loads(body)['preserved'])
        self.assertEqual(self.request('/ad'), (204, 'blocked', b''))
        self.assertEqual(self.request('/unknown')[0], 404)

    def test_private_ca_is_required(self):
        with self.assertRaises(ssl.SSLCertVerificationError):
            self.request('/content', trusted=False)

    def test_wg_config_export_and_no_private_keys_in_logs(self):
        output = subprocess.check_output([sys.executable, '-m', 'shiftrelay.android', 'client',
                                         '--endpoint', '127.0.0.1:51820', '--app', 'youtube'], env=self.env, cwd=ROOT, text=True)
        self.assertIn('IncludedApplications = org.shiftrelay.probe, com.google.android.youtube', output)
        direct = subprocess.check_output([sys.executable, '-m', 'shiftrelay.android', 'client',
                                         '--endpoint', '127.0.0.1:51820', '--app', 'youtube', '--no-probe'],
                                        env=self.env, cwd=ROOT, text=True)
        self.assertIn('IncludedApplications = com.google.android.youtube', direct)
        self.assertNotIn('org.shiftrelay.probe', direct)
        keys = json.loads((self.folder / 'ca/wireguard.conf').read_text())
        self.log.flush(); self.log.seek(0); log = self.log.read()
        self.assertNotIn(keys['client_key'], log)
        self.assertNotIn(keys['server_key'], log)
        self.assertNotIn('PrivateKey =', log)


if __name__ == '__main__':
    unittest.main()
