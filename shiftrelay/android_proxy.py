"""Owned virtual origin and aggregate diagnostics for the Android WireGuard lab."""
import asyncio
from ipaddress import IPv4Address
import json
import os
from pathlib import Path
import tempfile
import time
from urllib.parse import urlsplit

from mitmproxy import dns, http
from shiftrelay.policy import HOST, load as read_policy
from shiftrelay.proxy import ShiftRelay

LAB_HOSTS = ('relay-test.invalid', 'system-test.invalid')


class AndroidLab:
    def __init__(self):
        self.path = Path(os.environ.get('SHIFTRELAY_ANDROID_STATUS', '/status/android.json'))
        self.policy_path = Path(os.environ.get('SHIFTRELAY_POLICY', '/config/policy.json'))
        self.task = None
        self.discovery = os.environ.get('SHIFTRELAY_ANDROID_DISCOVERY', 'false') == 'true'
        self.destinations = {}
        self.discovery_path = Path(os.environ.get('SHIFTRELAY_CA', '/ca')) / 'destinations.json'
        self.started = int(time.time())
        self.counts = {'dns_queries': 0, 'tls_client_hellos': 0, 'tls_client_failures': 0,
                       'owned_requests': 0}

    def running(self):
        self.write()
        self.task = asyncio.create_task(self.pulse())

    async def pulse(self):
        while True:
            await asyncio.sleep(5)
            self.write()

    def write(self):
        value = {'schema': 1, 'transport': 'wireguard', 'started_at': self.started,
                 'updated_at': int(time.time()), 'counters': dict(self.counts),
                 'platform_ad_removal': 'unvalidated'}
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            fd, name = tempfile.mkstemp(dir=self.path.parent)
            with os.fdopen(fd, 'w') as f:
                json.dump(value, f)
            os.replace(name, self.path)
            if self.discovery:
                fd, name = tempfile.mkstemp(dir=self.discovery_path.parent)
                with os.fdopen(fd, 'w') as f:
                    json.dump({'schema': 1, 'updated_at': int(time.time()),
                               'source': 'dns-questions', 'hosts': self.destinations}, f)
                os.replace(name, self.discovery_path)
        except OSError:
            pass

    def inspected(self, host):
        try:
            p = read_policy(self.policy_path)
            return p['mode'] != 'bypass' and host in p['inspect_hosts'] and host not in p['bypass_hosts']
        except (OSError, ValueError):
            return False

    def dns_request(self, flow):
        # Resolve only our reserved fixture names. All real DNS uses mitmproxy's
        # normal resolver; no DNS ad blocklist or external test origin is needed.
        questions = flow.request.questions
        if len(questions) != 1:
            return
        question = questions[0]
        host = question.name.lower().rstrip('.')
        if self.discovery and HOST.fullmatch(host) and (host in self.destinations or len(self.destinations) < 128):
            self.destinations[host] = min(self.destinations.get(host, 0) + 1, 1000000)
        if host not in LAB_HOSTS:
            return
        self.counts['dns_queries'] += 1
        answers = ([dns.ResourceRecord.A(question.name, IPv4Address('10.0.0.2'), ttl=0)]
                   if question.type == dns.types.A else [])
        flow.response = flow.request.succeed(answers)

    def tls_clienthello(self, data):
        if self.inspected(data.client_hello.sni):
            self.counts['tls_client_hellos'] += 1

    def tls_failed_client(self, data):
        if self.inspected(data.context.client.sni):
            self.counts['tls_client_failures'] += 1
        # A TLS failure alone cannot distinguish pinning, CA rejection or network loss.

    def requestheaders(self, flow):
        if flow.request.host.lower().rstrip('.') not in LAB_HOSTS or flow.response is not None:
            return
        self.counts['owned_requests'] += 1
        path = urlsplit(flow.request.path).path
        status, body, typ = 200, b'', 'application/json'
        if flow.request.method not in ('GET', 'HEAD'):
            status, body = 405, b'{"error":"GET or HEAD only"}'
        elif path == '/content':
            body = b'{"fixture":"shiftrelay-owned-content","preserved":true}'
        elif path == '/ad':
            body = b'{"fixture":"shiftrelay-owned-ad","blocked":false}'
        elif path == '/':
            typ = 'text/html; charset=utf-8'
            body = b'<!doctype html><meta name="viewport" content="width=device-width"><title>ShiftRelay phone lab</title><h1>ShiftRelay phone lab</h1><p>Your request reached the owned fixture. Run the native ShiftRelay Probe app to test content and blocking.</p><p>This is not a YouTube, Netflix or other platform ad test.</p>'
        else:
            status, body = 404, b'{"error":"Unknown fixture"}'
        flow.response = http.Response.make(status, b'' if flow.request.method == 'HEAD' else body,
                                           {'Content-Type': typ, 'Cache-Control': 'no-store',
                                            'X-ShiftRelay-Lab': 'owned-fixture',
                                            'Content-Security-Policy': "default-src 'none'; frame-ancestors 'none'",
                                            'X-Content-Type-Options': 'nosniff'})

    def done(self):
        if self.task:
            self.task.cancel()


addons = [ShiftRelay(), AndroidLab()]
