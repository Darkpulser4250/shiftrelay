#!/usr/bin/env python3
"""CI-only: real Linux kernel WireGuard peer -> Docker -> owned HTTPS fixture.

Requires sudo, iproute2, wireguard-tools and the running Android Compose stack.
Creates a temporary network namespace; never changes the host's default route.
"""
import configparser
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]
COMPOSE = ['docker', 'compose', '-f', str(ROOT / 'compose.android.yaml')]


def call(*args, capture=False):
    result = subprocess.run([str(x) for x in args], check=True, text=True,
                            stdout=subprocess.PIPE if capture else None)
    return result.stdout if capture else None


def main():
    namespace = 'sr' + str(os.getpid())
    interface = namespace + 'wg'
    config = configparser.ConfigParser()
    secret = call(*COMPOSE, 'exec', '-T', 'android', 'python', '-m', 'shiftrelay.android',
                  'client', '--endpoint', '127.0.0.1:51820', capture=True)
    config.read_string(secret)
    created_ns = created_interface = False
    with tempfile.TemporaryDirectory(prefix='shiftrelay-wg-test-') as temporary:
        work = Path(temporary)
        private = work / 'peer.conf'
        with open(os.open(private, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), 'w') as f:
            f.write('[Interface]\nPrivateKey = ' + config['Interface']['PrivateKey'] +
                    '\n\n[Peer]\nPublicKey = ' + config['Peer']['PublicKey'] +
                    '\nAllowedIPs = 0.0.0.0/0\nEndpoint = 127.0.0.1:51820\n')
        ca = work / 'ca.crt'
        ca.write_text(call(*COMPOSE, 'exec', '-T', 'portal', 'cat', '/public/shiftrelay-ca.crt', capture=True))
        resolver = work / 'resolv.conf'; resolver.write_text('nameserver 10.0.0.53\noptions timeout:2 attempts:2\n')
        try:
            call('sudo', 'ip', 'netns', 'add', namespace); created_ns = True
            # WireGuard's UDP socket stays in the creation namespace, so the
            # isolated peer reaches Docker's loopback UDP mapping without NAT.
            call('sudo', 'ip', 'link', 'add', interface, 'type', 'wireguard'); created_interface = True
            call('sudo', 'wg', 'setconf', interface, private)
            call('sudo', 'ip', 'link', 'set', interface, 'netns', namespace); created_interface = False
            prefix = ['sudo', 'ip', 'netns', 'exec', namespace]
            call(*prefix, 'ip', 'link', 'set', 'lo', 'up')
            call(*prefix, 'ip', 'address', 'add', '10.0.0.1/32', 'dev', interface)
            call(*prefix, 'ip', 'link', 'set', interface, 'up')
            call(*prefix, 'ip', 'route', 'add', '10.0.0.0/24', 'dev', interface)
            call('sudo', 'mkdir', '-p', '/etc/netns/' + namespace)
            call('sudo', 'install', '-m', '644', resolver, '/etc/netns/' + namespace + '/resolv.conf')
            child = r'''
import http.client, json, socket, ssl, sys
assert socket.gethostbyname('relay-test.invalid') == '10.0.0.2'
def request(path, trusted=True):
    context = ssl.create_default_context(cafile=sys.argv[1] if trusted else None)
    connection = http.client.HTTPSConnection('relay-test.invalid', context=context, timeout=10)
    try:
        connection.request('GET', path)
        reply = connection.getresponse()
        return reply.status, reply.getheader('X-ShiftRelay'), reply.read()
    finally:
        connection.close()
status, _, body = request('/content')
assert status == 200 and json.loads(body)['preserved'] is True
assert request('/ad') == (204, 'blocked', b'')
try:
    request('/content', trusted=False)
except ssl.SSLCertVerificationError:
    pass
else:
    raise AssertionError('Untrusted private CA was accepted')
print('Real WireGuard peer: DNS, HTTPS, content preservation, blocking and CA rejection passed')
'''
            call(*prefix, sys.executable, '-c', child, ca)
            deadline = time.monotonic() + 12
            while True:
                value = json.loads(call(*COMPOSE, 'exec', '-T', 'android', 'python', '-m', 'shiftrelay.android', 'doctor', capture=True))
                if value['counters']['tls_client_failures'] >= 1 and value['counters']['owned_requests'] >= 1:
                    break
                if time.monotonic() > deadline:
                    raise AssertionError('Aggregate diagnostics did not reflect the live test')
                time.sleep(.5)
            logs = call(*COMPOSE, 'logs', '--no-color', 'android', capture=True)
            assert 'PrivateKey =' not in logs
            assert config['Interface']['PrivateKey'] not in logs
        finally:
            if created_interface:
                call('sudo', 'ip', 'link', 'delete', interface)
            if created_ns:
                call('sudo', 'ip', 'netns', 'delete', namespace)
                call('sudo', 'rm', '-f', '/etc/netns/' + namespace + '/resolv.conf')
                call('sudo', 'rmdir', '/etc/netns/' + namespace)


if __name__ == '__main__':
    main()
