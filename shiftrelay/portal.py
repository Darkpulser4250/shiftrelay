"""Consent-led enrollment + authenticated local status; never expose CA private keys."""
import hashlib
import hmac
import html
import json
import os
from pathlib import Path
import secrets
import ssl
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs
from shiftrelay import __version__
from shiftrelay.policy import load

STATIC = Path(__file__).with_name('static')


class Portal:
    def __init__(self, public, metrics, policy_path, key):
        if len(key) < 32:
            raise ValueError('Admin key must be at least 32 characters')
        self.public, self.metrics, self.policy_path = Path(public), Path(metrics), Path(policy_path)
        self.key = key
        self.sessions = {}
        self.lock = threading.Lock()

    def new_session(self):
        with self.lock:
            self.sessions = {k: v for k, v in self.sessions.items() if v['expires'] > time.monotonic()}
            if len(self.sessions) >= 200:
                self.sessions.pop(next(iter(self.sessions)))
            token = secrets.token_urlsafe(32)
            self.sessions[token] = {'csrf': secrets.token_urlsafe(24), 'expires': time.monotonic() + 600, 'consented': False}
            return token, self.sessions[token].copy()

    def session(self, token):
        with self.lock:
            value = self.sessions.get(token)
            return value.copy() if value and value['expires'] > time.monotonic() else None

    def consent(self, token, csrf):
        with self.lock:
            value = self.sessions.get(token)
            if not value or value['expires'] < time.monotonic() or not hmac.compare_digest(value['csrf'], csrf):
                return False
            value['consented'] = True
            return True

    def certificate(self):
        cert = (self.public / 'shiftrelay-ca.crt').read_text()
        # Defensive: exported content must be exactly a public X.509 certificate.
        if 'PRIVATE KEY' in cert or cert.count('BEGIN CERTIFICATE') != 1:
            raise ValueError('Invalid public certificate')
        der = ssl.PEM_cert_to_DER_cert(cert)
        fingerprint = ':'.join(f'{b:02X}' for b in hashlib.sha256(der).digest())
        return cert.encode(), fingerprint


def handler(app):
    class Handler(BaseHTTPRequestHandler):
        server_version = 'ShiftRelay'

        def setup(self):
            super().setup()
            self.connection.settimeout(5)

        def log_message(self, *_):
            pass

        def reply(self, status, data, mime='application/json', extra=None):
            body = json.dumps(data).encode() if mime == 'application/json' else data
            self.send_response(status)
            for k, v in {'Content-Type': mime, 'Content-Length': str(len(body)), 'Cache-Control': 'no-store',
                         'Content-Security-Policy': "default-src 'self'; script-src 'self'; style-src 'self'; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'",
                         'X-Content-Type-Options': 'nosniff', 'X-Frame-Options': 'DENY',
                         **(extra or {})}.items():
                self.send_header(k, v)
            self.end_headers()
            self.wfile.write(body)

        def admin(self):
            return hmac.compare_digest(self.headers.get('Authorization', '').encode(), ('Bearer ' + app.key).encode())

        def token(self):
            for part in self.headers.get('Cookie', '').split(';'):
                if part.strip().startswith('shiftrelay_session='):
                    return part.strip().split('=', 1)[1]
            return ''

        def do_GET(self):
            if self.path == '/healthz':
                return self.reply(200, {'status': 'ok', 'version': __version__})
            if self.path in ('/', '/app.js', '/style.css'):
                name, mime = {'/': ('index.html', 'text/html; charset=utf-8'), '/app.js': ('app.js', 'text/javascript'), '/style.css': ('style.css', 'text/css')}[self.path]
                return self.reply(200, (STATIC / name).read_bytes(), mime)
            if self.path == '/enroll':
                token, session = app.new_session()
                try:
                    _, fingerprint = app.certificate()
                except (OSError, ValueError):
                    fingerprint = 'Certificate not ready. Start the proxy first and reload.'
                page = '''<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width"><title>Join ShiftRelay</title><link rel="stylesheet" href="/style.css"></head><body><main class="enrollment"><p class="eyebrow">OPTIONAL DEVICE ENROLLMENT</p><h1>Your choice.<br>Your connection.</h1><section class="card"><h2>Allow selective HTTPS inspection?</h2><p>This server can read and change traffic to hosts its owner explicitly enables, if your app trusts its certificate. That can include sensitive content sent to those hosts. Network membership alone grants no inspection permission.</p><p>Downloading a certificate does not install or trust it. Your operating system requires additional confirmation. Some apps will still refuse inspection.</p><p>Compare this SHA-256 certificate fingerprint with the server owner using a separate trusted channel:</p><pre>FINGERPRINT</pre><form method="post" action="/enroll/consent"><input type="hidden" name="csrf" value="CSRF"><button name="choice" value="inspect">I understand — get the public certificate</button> <button class="secondary" name="choice" value="bypass">Continue without inspection</button></form></section><p>For bypass, leave your device proxy disabled or use your normal network. This page cannot change your router, proxy, VPN, or trust settings.</p></main></body></html>'''
                page = page.replace('FINGERPRINT', html.escape(fingerprint)).replace('CSRF', session['csrf'])
                return self.reply(200, page.encode(), 'text/html; charset=utf-8',
                                  {'Set-Cookie': f'shiftrelay_session={token}; HttpOnly; SameSite=Strict; Path=/enroll; Max-Age=600'})
            if self.path == '/enroll/ca.crt':
                session = app.session(self.token())
                if not session or not session['consented']:
                    return self.reply(403, {'error': 'Open /enroll and consent first'})
                try:
                    cert, _ = app.certificate()
                    return self.reply(200, cert, 'application/x-x509-ca-cert', {'Content-Disposition': 'attachment; filename="shiftrelay-ca.crt"'})
                except (OSError, ValueError):
                    return self.reply(503, {'error': 'Certificate unavailable'})
            if not self.admin():
                return self.reply(401, {'error': 'Unauthorized'})
            if self.path == '/v1/status':
                try:
                    policy = load(app.policy_path)
                    try:
                        metrics = json.loads(app.metrics.read_text())
                    except (OSError, ValueError):
                        metrics = None
                    _, fingerprint = app.certificate()
                    return self.reply(200, {'version': __version__, 'policy': policy, 'metrics': metrics, 'ca_sha256': fingerprint})
                except (OSError, ValueError):
                    return self.reply(503, {'error': 'Proxy certificate or policy not ready'})
            return self.reply(404, {'error': 'Not found'})

        def do_POST(self):
            if self.path != '/enroll/consent':
                return self.reply(404, {'error': 'Not found'})
            if self.headers.get('Content-Type', '').split(';')[0] != 'application/x-www-form-urlencoded':
                return self.reply(415, {'error': 'Form required'})
            try:
                length = int(self.headers.get('Content-Length', '-1'))
                if self.headers.get('Transfer-Encoding') or not 0 < length < 2048:
                    raise ValueError()
                form = parse_qs(self.rfile.read(length).decode(), strict_parsing=True)
                if form.get('choice') == ['bypass']:
                    return self.reply(200, b'Inspection declined. Leave your device proxy disabled; no router or OS settings have been changed.', 'text/plain')
                csrf = form.get('csrf', [''])[0]
                if form.get('choice') != ['inspect'] or not app.consent(self.token(), csrf):
                    return self.reply(403, {'error': 'Enrollment expired or invalid; reopen /enroll'})
                return self.reply(303, b'', 'text/plain', {'Location': '/enroll/ca.crt'})
            except (ValueError, UnicodeError):
                return self.reply(400, {'error': 'Invalid form'})
    return Handler


class Server(ThreadingHTTPServer):
    daemon_threads = True
    def __init__(self, address, request_handler):
        self.slots = threading.BoundedSemaphore(32)
        super().__init__(address, request_handler)

    def process_request(self, request, client_address):
        if not self.slots.acquire(blocking=False):
            self.shutdown_request(request)
            return
        try:
            super().process_request(request, client_address)
        except BaseException:
            self.slots.release()
            raise

    def process_request_thread(self, request, client_address):
        try:
            super().process_request_thread(request, client_address)
        finally:
            self.slots.release()


def main():
    app = Portal(os.environ.get('SHIFTRELAY_PUBLIC', '/public'), os.environ.get('SHIFTRELAY_METRICS', '/status/metrics.json'),
                 os.environ.get('SHIFTRELAY_POLICY', '/config/policy.json'), os.environ.get('SHIFTRELAY_ADMIN_KEY', ''))
    server = Server((os.environ.get('SHIFTRELAY_PORTAL_BIND', '0.0.0.0'), int(os.environ.get('SHIFTRELAY_PORTAL_PORT', '8787'))), handler(app))
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == '__main__':
    main()
