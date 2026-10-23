"""Single-phone WireGuard lab. Peer secrets are exported only by explicit CLI."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import ssl
import stat
import sys
import time

from shiftrelay.policy import HOST, load, tls_allow_hosts

PROBE_PACKAGE = 'org.shiftrelay.probe'
PACKAGES = {
    'probe': PROBE_PACKAGE,
    'youtube': 'com.google.android.youtube',
    'netflix': 'com.netflix.mediaclient',
    'hulu': 'com.hulu.plus',
    'instagram': 'com.instagram.android',
    'facebook': 'com.facebook.katana',
}


def endpoint(value):
    # Prevent config injection; the endpoint must be supplied by the owner.
    import ipaddress
    if not isinstance(value, str) or len(value) > 300:
        raise ValueError('Use HOST:PORT or [IPv6]:PORT')
    match = re.fullmatch(r'(\[[0-9a-fA-F:]+\]|[a-z0-9.-]+):([0-9]{1,5})', value)
    if not match or not 1 <= int(match[2]) <= 65535:
        raise ValueError('Use HOST:PORT or [IPv6]:PORT')
    if match[1].startswith('['):
        ipaddress.IPv6Address(match[1][1:-1])
    elif not HOST.fullmatch(match[1]):
        raise ValueError('Invalid endpoint host')
    return value


def read_keys(path):
    import mitmproxy_rs
    with open(path) as f:
        info = os.fstat(f.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_mode & 0o077 or info.st_size > 4096:
            raise ValueError('WireGuard keys must be an owner-only regular file')
        value = json.load(f)
    if not isinstance(value, dict) or set(value) != {'server_key', 'client_key'}:
        raise ValueError('Invalid WireGuard key file')
    for key in value.values():
        mitmproxy_rs.wireguard.pubkey(key)
    return value


def ensure_keys(path):
    import mitmproxy_rs
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        return read_keys(path)
    with os.fdopen(fd, 'w') as f:
        json.dump({'server_key': mitmproxy_rs.wireguard.genkey(),
                   'client_key': mitmproxy_rs.wireguard.genkey()}, f)
    return read_keys(path)


def client_config(keys, remote, apps):
    import mitmproxy_rs
    remote = endpoint(remote)
    selected = [PROBE_PACKAGE]
    for app in apps:
        if app not in PACKAGES:
            raise ValueError('Choose a supported app alias')
        if PACKAGES[app] not in selected:
            selected.append(PACKAGES[app])
    # Capture IPv6 as well: never silently send selected-app IPv6 outside the VPN.
    # Upstream IPv6 forwarding remains limited; this lab primarily tests IPv4.
    return ('[Interface]\nPrivateKey = ' + keys['client_key'] +
            '\nAddress = 10.0.0.1/32, fd00:7368:6966::1/128\nDNS = 10.0.0.53\nMTU = 1280\n' +
            'IncludedApplications = ' + ', '.join(selected) +
            '\n\n[Peer]\nPublicKey = ' + mitmproxy_rs.wireguard.pubkey(keys['server_key']) +
            '\nAllowedIPs = 0.0.0.0/0, ::/0\nEndpoint = ' + remote +
            '\nPersistentKeepalive = 25\n')


def run():
    from mitmproxy.certs import CertStore
    from mitmproxy.tools.main import mitmdump
    import shutil
    os.umask(0o077)
    ca = Path(os.environ.get('SHIFTRELAY_CA', '/ca'))
    ca.mkdir(parents=True, exist_ok=True)
    ensure_keys(ca / 'wireguard.conf')
    CertStore.from_store(ca, 'mitmproxy', 2048)
    public = Path(os.environ.get('SHIFTRELAY_PUBLIC', '/public'))
    public.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(ca / 'mitmproxy-ca-cert.pem', public / 'shiftrelay-ca.crt')
    os.chmod(public / 'shiftrelay-ca.crt', 0o644)
    policy = load(os.environ.get('SHIFTRELAY_POLICY', '/config/policy.json'))
    port = int(os.environ.get('SHIFTRELAY_WG_PORT', '51820'))
    if not 1 <= port <= 65535:
        raise ValueError('Invalid WireGuard port')
    args = ['--mode', f'wireguard:{ca / "wireguard.conf"}@{port}',
            '--listen-host', os.environ.get('SHIFTRELAY_LISTEN', '0.0.0.0'),
            '--set', 'confdir=' + str(ca), '--set', 'flow_detail=0',
            '--set', 'termlog_verbosity=error', '--set', 'ssl_insecure=false',
            '--set', 'connection_strategy=lazy', '--set', 'upstream_cert=false',
            '--set', 'stream_large_bodies=128k',
            '-s', str(Path(__file__).with_name('android_proxy.py'))]
    for host in tls_allow_hosts(policy):
        args.extend(['--allow-hosts', host])
    mitmdump(args)


def doctor():
    path = Path(os.environ.get('SHIFTRELAY_ANDROID_STATUS', '/status/android.json'))
    value = json.loads(path.read_text())
    if value.get('schema') != 1 or time.time() - value['updated_at'] > 45:
        raise ValueError('Android server heartbeat is stale')
    cert = (Path(os.environ.get('SHIFTRELAY_PUBLIC', '/public')) / 'shiftrelay-ca.crt').read_text()
    if 'PRIVATE KEY' in cert:
        raise ValueError('Invalid public CA')
    value['ca_sha256'] = hashlib.sha256(ssl.PEM_cert_to_DER_cert(cert)).hexdigest().upper()
    return value


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    sub.add_parser('run')
    sub.add_parser('doctor')
    sub.add_parser('destinations', help='Read private, opt-in DNS hostname discovery; never URLs or app IDs')
    client = sub.add_parser('client', help='Export SECRET peer config to stdout; redirect to a private file')
    client.add_argument('--endpoint', required=True)
    client.add_argument('--app', choices=PACKAGES, action='append', default=[])
    args = parser.parse_args()
    try:
        if args.command == 'run':
            run()
        elif args.command == 'doctor':
            print(json.dumps(doctor(), indent=2))
        elif args.command == 'destinations':
            path = Path(os.environ.get('SHIFTRELAY_CA', '/ca')) / 'destinations.json'
            if path.stat().st_size > 65536:
                raise ValueError('Oversize discovery record')
            value = json.loads(path.read_text())
            if set(value) != {'schema', 'updated_at', 'source', 'hosts'} or value['schema'] != 1 or value['source'] != 'dns-questions':
                raise ValueError('Invalid discovery record')
            if not isinstance(value['hosts'], dict) or len(value['hosts']) > 128:
                raise ValueError('Invalid discovery record')
            for host, count in value['hosts'].items():
                if not HOST.fullmatch(host) or type(count) is not int or not 0 <= count <= 1000000:
                    raise ValueError('Invalid discovery record')
            print(json.dumps(value, indent=2))
        else:
            keys = read_keys(Path(os.environ.get('SHIFTRELAY_CA', '/ca')) / 'wireguard.conf')
            sys.stdout.write(client_config(keys, args.endpoint, args.app))
    except (OSError, ValueError, KeyError, TypeError):
        # Never include a config file's contents or key in an exception/log.
        parser.exit(1, 'Android lab configuration unavailable or invalid. Check private state and endpoint.\n')


if __name__ == '__main__':
    main()
