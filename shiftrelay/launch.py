"""Create a per-install CA; share its PUBLIC certificate only with enrollment."""
import os
from pathlib import Path
import shutil
from mitmproxy.certs import CertStore
from shiftrelay.policy import load, tls_allow_hosts
from mitmproxy.tools.main import mitmdump


def main():
    os.umask(0o077)
    directory = Path(os.environ.get('SHIFTRELAY_CA', '/ca'))
    directory.mkdir(parents=True, exist_ok=True)
    CertStore.from_store(directory, 'mitmproxy', 2048)
    public = Path(os.environ.get('SHIFTRELAY_PUBLIC', '/public'))
    public.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(directory / 'mitmproxy-ca-cert.pem', public / 'shiftrelay-ca.crt')
    os.chmod(public / 'shiftrelay-ca.crt', 0o644)
    config = load(os.environ.get('SHIFTRELAY_POLICY', '/config/policy.json'))
    auth = os.environ.get('SHIFTRELAY_PROXY_AUTH', '')
    if ':' not in auth or len(auth.split(':', 1)[1]) < 24:
        raise ValueError('Run scripts/setup.py to generate proxy credentials')
    args = ['--mode', 'regular', '--listen-host', os.environ.get('SHIFTRELAY_LISTEN', '0.0.0.0'),
            '--listen-port', os.environ.get('SHIFTRELAY_PROXY_PORT', '8080'),
            '--set', 'confdir=' + str(directory), '--set', 'flow_detail=0',
            '--set', 'termlog_verbosity=error', '--set', 'ssl_insecure=false',
            '--set', 'connection_strategy=lazy', '--set', 'stream_large_bodies=128k',
            '--proxyauth', auth,
            '-s', str(Path(__file__).with_name('proxy.py'))]
    for host in tls_allow_hosts(config):
        args.extend(['--allow-hosts', host])
    upstream_ca = os.environ.get('SHIFTRELAY_UPSTREAM_CA')
    if upstream_ca:
        args.extend(['--set', 'ssl_verify_upstream_trusted_ca=' + upstream_ca])
    mitmdump(args)


if __name__ == '__main__':
    main()
