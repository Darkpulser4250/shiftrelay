"""Real local HTTPS server -> real mitmdump -> HTTPS client. No external traffic."""
import base64
from datetime import datetime, timedelta, timezone
import http.client
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
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID

ROOT = Path(__file__).resolve().parents[1]


def free_port():
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0)); return sock.getsockname()[1]


class ProxyIntegration(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(); cls.folder = Path(cls.temp.name)
        cls.hits = []
        key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, 'localhost')])
        now = datetime.now(timezone.utc)
        cert = (x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(key.public_key())
                .serial_number(x509.random_serial_number()).not_valid_before(now - timedelta(days=1)).not_valid_after(now + timedelta(days=2))
                .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
                .add_extension(x509.SubjectAlternativeName([x509.DNSName('localhost')]), critical=False).sign(key, hashes.SHA256()))
        cls.origin_ca = cls.folder / 'origin.crt'
        cls.origin_ca.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
        key_file = cls.folder / 'origin.key'
        key_file.write_bytes(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))

        class Origin(BaseHTTPRequestHandler):
            def log_message(self, *_): pass
            def do_GET(self):
                cls.hits.append(self.path)
                body = ((ROOT / 'fixtures/owned-vod.m3u8').read_bytes() if self.path == '/vod.m3u8' else
                        b'x' * (2*1024*1024) if self.path == '/large' else b'original-content')
                self.send_response(200)
                self.send_header('Content-Length', str(len(body)))
                self.send_header('Content-Type', 'application/vnd.apple.mpegurl' if self.path == '/vod.m3u8' else 'text/plain')
                self.end_headers(); self.wfile.write(body)

        cls.origin = ThreadingHTTPServer(('127.0.0.1', 0), Origin)
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER); context.load_cert_chain(cls.origin_ca, key_file)
        cls.origin.socket = context.wrap_socket(cls.origin.socket, server_side=True)
        cls.thread = threading.Thread(target=cls.origin.serve_forever, daemon=True); cls.thread.start()
        cls.port = free_port()
        cls.config = cls.folder / 'policy.json'; cls.config.write_bytes((ROOT / 'fixtures/policy.demo.json').read_bytes())
        env = dict(os.environ, SHIFTRELAY_POLICY=str(cls.config), SHIFTRELAY_CA=str(cls.folder / 'ca'), SHIFTRELAY_PUBLIC=str(cls.folder / 'public'),
                   SHIFTRELAY_METRICS=str(cls.folder / 'metrics.json'), SHIFTRELAY_PROXY_PORT=str(cls.port), SHIFTRELAY_LISTEN='127.0.0.1',
                   SHIFTRELAY_PROXY_AUTH='lab:' + 'x'*32, SHIFTRELAY_UPSTREAM_CA=str(cls.origin_ca))
        cls.log = open(cls.folder / 'proxy.log', 'w+')
        cls.process = subprocess.Popen([sys.executable, '-m', 'shiftrelay.launch'], cwd=ROOT, env=env, stdout=cls.log, stderr=cls.log)
        deadline = time.monotonic() + 12
        while time.monotonic() < deadline:
            try:
                with socket.create_connection(('127.0.0.1', cls.port), timeout=.2): pass
                if (cls.folder / 'public/shiftrelay-ca.crt').exists(): return
            except OSError:
                pass
            if cls.process.poll() is not None: break
            time.sleep(.1)
        cls.log.seek(0)
        cls.tearDownClass()
        raise RuntimeError('Proxy did not start')

    @classmethod
    def tearDownClass(cls):
        if getattr(cls, 'process', None):
            cls.process.terminate()
            try: cls.process.wait(timeout=5)
            except subprocess.TimeoutExpired: cls.process.kill(); cls.process.wait()
        if getattr(cls, 'origin', None): cls.origin.shutdown(); cls.origin.server_close(); cls.thread.join()
        if getattr(cls, 'log', None): cls.log.close()
        cls.temp.cleanup()

    def request(self, path, ca=None, auth=True):
        context = ssl.create_default_context(cafile=str(ca or self.folder / 'public/shiftrelay-ca.crt'))
        c = http.client.HTTPSConnection('127.0.0.1', self.port, context=context, timeout=5)
        headers = {'Proxy-Authorization': 'Basic ' + base64.b64encode(('lab:' + 'x'*32).encode()).decode()} if auth else {}
        c.set_tunnel('localhost', self.origin.server_port, headers=headers)
        try:
            c.request('GET', path); response = c.getresponse(); return response.status, dict(response.headers), response.read()
        finally:
            c.close()

    def test_01_blocks_exact_ad_request_without_contacting_origin(self):
        before = len(self.hits)
        status, _, body = self.request('/ads.js')
        self.assertEqual(status, 204); self.assertEqual(body, b''); self.assertEqual(len(self.hits), before)

    def test_02_preserves_content(self):
        self.assertEqual(self.request('/content')[2], b'original-content')

    def test_03_rewrites_owned_manifest(self):
        status, headers, body = self.request('/vod.m3u8')
        self.assertEqual(status, 200); self.assertNotIn(b'ad-000.ts', body); self.assertIn(b'content-001.ts', body)
        self.assertEqual(headers.get('x-shiftrelay'), 'owned-hls-rewritten')

    def test_04_rejects_untrusted_proxy_certificate(self):
        with self.assertRaises(ssl.SSLCertVerificationError):
            self.request('/content', self.origin_ca)

    def test_05_requires_proxy_auth(self):
        with self.assertRaises(OSError): self.request('/content', auth=False)

    def test_05b_streams_large_response_without_truncation(self):
        self.assertEqual(len(self.request('/large')[2]), 2*1024*1024)

    def test_06_observe_and_bypass(self):
        p = json.loads(self.config.read_text()); p['mode'] = 'observe'; self.config.write_text(json.dumps(p))
        time.sleep(1.1)
        self.assertEqual(self.request('/ads.js')[0], 200)
        p['mode'] = 'bypass'; self.config.write_text(json.dumps(p)); time.sleep(1.1)
        # The first new request triggers reload; open again to test a newly tunnelled session.
        try: self.request('/content')
        except ssl.SSLCertVerificationError: pass
        # In bypass the client must see and trust the real origin, not ShiftRelay's CA.
        self.assertEqual(self.request('/ads.js', self.origin_ca)[0], 200)
        with self.assertRaises(ssl.SSLCertVerificationError): self.request('/content')


if __name__ == '__main__': unittest.main()
