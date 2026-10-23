"""Real TLS response rewriting against a local origin impersonating test domains.

All outbound connections are redirected to that origin by a test-only addon.
No real platform, streaming account or device is contacted.
"""
import base64
from datetime import datetime, timedelta, timezone
import gzip
import http.client
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import socket
import ssl
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID
from test_platforms import youtube, instagram

ROOT = Path(__file__).resolve().parents[1]


class PlatformIntegration(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(); cls.folder = Path(cls.temp.name)
        cls.names = ['youtubei.googleapis.com', 'i.instagram.com', 'graph.facebook.com']
        key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, 'Owned platform fixture')])
        now = datetime.now(timezone.utc)
        cert = (x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(key.public_key())
                .serial_number(x509.random_serial_number()).not_valid_before(now - timedelta(days=1))
                .not_valid_after(now + timedelta(days=1))
                .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
                .add_extension(x509.SubjectAlternativeName([x509.DNSName(host) for host in cls.names]), critical=False)
                .sign(key, hashes.SHA256()))
        cls.ca = cls.folder / 'origin.crt'; cls.ca.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
        private = cls.folder / 'origin.key'
        private.write_bytes(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
        cls.origin_mode = 'json'

        class Origin(BaseHTTPRequestHandler):
            protocol_version = 'HTTP/1.1'
            def log_message(self, *_): pass
            def do_POST(self):
                self.rfile.read(int(self.headers.get('Content-Length', '0')))
                self.do_GET()
            def do_GET(self):
                body = (json.dumps(youtube()).encode() if self.path.startswith('/youtubei/') else
                        json.dumps(instagram()).encode() if self.path.startswith('/api/v1/feed') else
                        b'{"data":{"category":"SPONSORED","cursor":"keep","node":{"id":"owned-ad"}}}\n')
                typ, encoding = 'application/json', None
                if cls.origin_mode == 'gzip': body = gzip.compress(body); encoding = 'gzip'
                if cls.origin_mode == 'binary': body = b'\x0a\x03opaque'; typ = 'application/x-protobuf'
                if cls.origin_mode == 'chunked-oversize': body = b'x' * (2 * 1024 * 1024 + 1024)
                self.send_response(200)
                self.send_header('Content-Type', typ)
                self.send_header('ETag', 'fixture-etag')
                if encoding: self.send_header('Content-Encoding', encoding)
                if cls.origin_mode == 'chunked-oversize':
                    self.send_header('Transfer-Encoding', 'chunked')
                    self.end_headers()
                    for i in range(0, len(body), 32768):
                        chunk = body[i:i+32768]
                        self.wfile.write(f'{len(chunk):x}\r\n'.encode() + chunk + b'\r\n')
                    self.wfile.write(b'0\r\n\r\n')
                else:
                    self.send_header('Content-Length', str(len(body))); self.end_headers(); self.wfile.write(body)

        cls.origin = ThreadingHTTPServer(('127.0.0.1', 0), Origin)
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER); context.load_cert_chain(cls.ca, private)
        cls.origin.socket = context.wrap_socket(cls.origin.socket, server_side=True)
        cls.thread = threading.Thread(target=cls.origin.serve_forever, daemon=True); cls.thread.start()
        reroute = cls.folder / 'local_origin.py'
        reroute.write_text(f'def server_connect(data):\n    data.server.address = ("127.0.0.1", {cls.origin.server_port})\n')
        cls.config = cls.folder / 'policy.json'
        cls.policy = dict(schema=1, version=1, mode='filter', inspect_hosts=cls.names, bypass_hosts=[],
                          block_rules=[], owned_hls_hosts=[], response_adapters=['youtube_player', 'instagram_timeline', 'facebook_graphql'])
        cls.config.write_text(json.dumps(cls.policy))
        with socket.socket() as sock:
            sock.bind(('127.0.0.1', 0)); cls.port = sock.getsockname()[1]
        env = dict(os.environ, SHIFTRELAY_CA=str(cls.folder / 'ca'), SHIFTRELAY_PUBLIC=str(cls.folder / 'public'),
                   SHIFTRELAY_POLICY=str(cls.config), SHIFTRELAY_METRICS=str(cls.folder / 'metrics.json'),
                   SHIFTRELAY_PROXY_PORT=str(cls.port), SHIFTRELAY_LISTEN='127.0.0.1',
                   SHIFTRELAY_PROXY_AUTH='lab:' + 'x'*32, SHIFTRELAY_UPSTREAM_CA=str(cls.ca))
        # Add the local-only transport hook before the real core addon.
        runner = cls.folder / 'run.py'
        runner.write_text('from shiftrelay.launch import main\nfrom mitmproxy.tools import main as entry\n'
                          'original = entry.mitmdump\n'
                          f'entry.mitmdump = lambda args: original([*args, "-s", {str(reroute)!r}])\n'
                          'import shiftrelay.launch\nshiftrelay.launch.mitmdump = entry.mitmdump\nmain()\n')
        cls.log = open(cls.folder / 'proxy.log', 'w+')
        env['PYTHONPATH'] = str(ROOT)
        cls.process = subprocess.Popen([sys.executable, runner], cwd=ROOT, env=env, stdout=cls.log, stderr=cls.log)
        deadline = time.monotonic() + 12
        while time.monotonic() < deadline:
            try:
                with socket.create_connection(('127.0.0.1', cls.port), timeout=.2): return
            except OSError:
                time.sleep(.1)
            if cls.process.poll() is not None: break
        cls.log.seek(0); error = cls.log.read()
        cls.tearDownClass(); raise RuntimeError('Platform fixture failed to start: ' + error)

    @classmethod
    def tearDownClass(cls):
        cls.process.terminate()
        try: cls.process.wait(timeout=5)
        except subprocess.TimeoutExpired: cls.process.kill(); cls.process.wait()
        cls.origin.shutdown(); cls.origin.server_close(); cls.thread.join()
        cls.log.close(); cls.temp.cleanup()

    def request(self, host, path):
        context = ssl.create_default_context(cafile=str(self.folder / 'public/shiftrelay-ca.crt'))
        connection = http.client.HTTPSConnection('127.0.0.1', self.port, context=context, timeout=8)
        auth = base64.b64encode(('lab:' + 'x'*32).encode()).decode()
        connection.set_tunnel(host, 443, headers={'Proxy-Authorization': 'Basic ' + auth})
        try:
            connection.request('POST', path, body=b'{}', headers={'Content-Type': 'application/json'})
            reply = connection.getresponse(); return reply.status, dict(reply.headers), reply.read()
        finally:
            connection.close()

    def test_01_filters_three_schemas_over_real_https(self):
        _, headers, body = self.request(self.names[0], '/youtubei/v1/player?key=not-logged')
        edited = json.loads(body)
        self.assertNotIn('adSlots', edited)
        self.assertEqual(edited['streamingData'], youtube()['streamingData'])
        self.assertNotIn('etag', {key.lower(): value for key, value in headers.items()})
        self.assertEqual(headers.get('cache-control'), 'no-store')
        _, _, body = self.request(self.names[1], '/api/v1/feed/timeline/')
        self.assertEqual(len(json.loads(body)['feed_items']), 2)
        _, _, body = self.request(self.names[2], '/graphql')
        self.assertEqual(json.loads(body)['data'], {'category': 'SPONSORED', 'cursor': 'keep'})

    def test_02_gzip_and_unsupported_binary_passthrough(self):
        type(self).origin_mode = 'gzip'
        try:
            _, headers, body = self.request(self.names[0], '/youtubei/v1/player')
            self.assertEqual(headers.get('Content-Encoding', headers.get('content-encoding')), 'gzip')
            self.assertNotIn('adSlots', json.loads(gzip.decompress(body)))
            type(self).origin_mode = 'binary'
            self.assertEqual(self.request(self.names[0], '/youtubei/v1/player')[2], b'\x0a\x03opaque')
        finally:
            type(self).origin_mode = 'json'

    def test_03_chunked_body_over_limit_is_not_truncated(self):
        type(self).origin_mode = 'chunked-oversize'
        try:
            _, _, body = self.request(self.names[0], '/youtubei/v1/player')
            self.assertEqual(body, b'x' * (2 * 1024 * 1024 + 1024))
        finally:
            type(self).origin_mode = 'json'

    def test_04_observe_preserves_bytes_and_does_not_claim_removed_units(self):
        variant = {**self.policy, 'mode': 'observe'}
        self.config.write_text(json.dumps(variant)); time.sleep(1.1)
        _, _, body = self.request(self.names[0], '/youtubei/v1/player')
        self.assertEqual(body, json.dumps(youtube()).encode())
        metrics = json.loads((self.folder / 'metrics.json').read_text())
        counters = metrics['response_adapters']['youtube_player']
        self.assertEqual(counters['removed_units'], 6)
        self.assertEqual(counters['candidate_units'], 9)
        self.assertEqual(counters['binary_unhandled'], 1)
        self.assertEqual(counters['oversize'], 1)
        self.assertNotIn('not-logged', json.dumps(metrics))


if __name__ == '__main__':
    unittest.main()
