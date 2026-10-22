import http.client
import json
from pathlib import Path
import re
import tempfile
import threading
import unittest
from urllib.parse import urlencode
from shiftrelay.portal import Portal, Server, handler


class PortalTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        from mitmproxy.certs import CertStore
        CertStore.from_store(self.root, 'mitmproxy', 2048)
        (self.root / 'shiftrelay-ca.crt').write_bytes((self.root / 'mitmproxy-ca-cert.pem').read_bytes())
        self.app = Portal(self.root, self.root / 'metrics.json', Path(__file__).resolve().parents[1] / 'config/policy.json', 'a'*40)
        self.server = Server(('127.0.0.1', 0), handler(self.app))
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True); self.thread.start()

    def tearDown(self):
        self.server.shutdown(); self.server.server_close(); self.thread.join(); self.temp.cleanup()

    def request(self, method, path, body=None, headers=None):
        c = http.client.HTTPConnection('127.0.0.1', self.server.server_port, timeout=3)
        c.request(method, path, body, headers or {})
        r = c.getresponse(); result = (r.status, dict(r.headers), r.read()); c.close(); return result

    def test_admin_required(self):
        self.assertEqual(self.request('GET', '/v1/status')[0], 401)
        self.assertEqual(self.request('GET', '/v1/status', headers={'Authorization': 'Bearer ' + 'a'*40})[0], 200)

    def test_enrollment_requires_consent_and_csrf(self):
        self.assertEqual(self.request('GET', '/enroll/ca.crt')[0], 403)
        status, headers, page = self.request('GET', '/enroll')
        cookie = headers['Set-Cookie'].split(';')[0]
        csrf = re.search(r'name="csrf" value="([^"]+)"', page.decode()).group(1)
        bad = self.request('POST', '/enroll/consent', urlencode({'choice': 'inspect', 'csrf': 'bad'}), {'Cookie': cookie, 'Content-Type': 'application/x-www-form-urlencoded'})
        self.assertEqual(bad[0], 403)
        good = self.request('POST', '/enroll/consent', urlencode({'choice': 'inspect', 'csrf': csrf}), {'Cookie': cookie, 'Content-Type': 'application/x-www-form-urlencoded'})
        self.assertEqual(good[0], 303)
        cert = self.request('GET', '/enroll/ca.crt', headers={'Cookie': cookie})
        self.assertEqual(cert[0], 200); self.assertNotIn(b'PRIVATE KEY', cert[2])

    def test_private_material_is_never_served(self):
        for path in ['/mitmproxy-ca.pem', '/enroll/../mitmproxy-ca.pem', '/ca/mitmproxy-ca.pem']:
            self.assertEqual(self.request('GET', path)[0], 401)


if __name__ == '__main__':
    unittest.main()
