"""Opt-in signed rule updates. Changes rules only, never code or trust scope."""
import argparse
import base64
import copy
import json
import os
from pathlib import Path
import tempfile
import time
from urllib.request import urlopen
from urllib.parse import urlsplit
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from cryptography.hazmat.primitives.serialization import load_pem_public_key
from shiftrelay.policy import decide, load, validate

LIMIT = 262144


def approved_update(current, envelope_bytes, public_pem, now=None):
    if len(envelope_bytes) > LIMIT:
        raise ValueError('Catalog too large')
    envelope = json.loads(envelope_bytes)
    if not isinstance(envelope, dict) or set(envelope) != {'payload_b64', 'signature_b64'}:
        raise ValueError('Invalid signed envelope')
    payload = base64.b64decode(envelope['payload_b64'], validate=True)
    signature = base64.b64decode(envelope['signature_b64'], validate=True)
    key = load_pem_public_key(public_pem)
    if not isinstance(key, Ed25519PublicKey):
        raise ValueError('Expected pinned Ed25519 public key')
    key.verify(signature, payload)
    document = json.loads(payload)
    if set(document) != {'version', 'expires', 'block_rules', 'canaries'}:
        raise ValueError('Unexpected catalog fields')
    now = time.time() if now is None else now
    if type(document['expires']) is not int or not now < document['expires'] <= now + 31*86400:
        raise ValueError('Expired or overlong catalog lifetime')
    if type(document['version']) is not int or document['version'] <= current['version']:
        raise ValueError('Replay or downgrade refused')
    candidate = copy.deepcopy(current)
    candidate.update(version=document['version'], block_rules=document['block_rules'])
    validate(candidate)  # Cannot add hosts, activate filtering, or alter TLS bypasses.
    canaries = document['canaries']
    if not isinstance(canaries, list) or not 1 <= len(canaries) <= 100:
        raise ValueError('1..100 canaries required')
    filtering = copy.deepcopy(candidate); filtering['mode'] = 'filter'
    for canary in canaries:
        if not isinstance(canary, dict) or set(canary) != {'host', 'path', 'method', 'expected'} or any(not isinstance(v, str) for v in canary.values()):
            raise ValueError('Invalid canary')
        if canary['expected'] not in ('pass', 'block') or decide(filtering, canary['host'], canary['path'], canary['method'])['action'] != canary['expected']:
            raise ValueError('Catalog canary failed')
    return candidate


def install(path, candidate):
    path = Path(path)
    fd, temporary = tempfile.mkstemp(dir=path.parent)
    try:
        with os.fdopen(fd, 'w') as f:
            json.dump(candidate, f, indent=2); f.write('\n'); f.flush(); os.fsync(f.fileno())
        # Backup is for operator rollback. Never automatically execute downloaded scripts.
        backup = path.with_suffix('.previous.json')
        backup.write_bytes(path.read_bytes())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary): os.unlink(temporary)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--catalog-url', required=True)
    parser.add_argument('--public-key', type=Path, required=True)
    parser.add_argument('--policy', type=Path, default=Path('config/policy.json'))
    args = parser.parse_args()
    url = urlsplit(args.catalog_url)
    if url.scheme != 'https' or url.username or url.password:
        parser.error('Use an HTTPS catalog URL without embedded credentials')
    with urlopen(args.catalog_url, timeout=10) as response:
        if urlsplit(response.url).scheme != 'https':
            raise ValueError('Insecure redirect refused')
        envelope = response.read(LIMIT + 1)
    candidate = approved_update(load(args.policy), envelope, args.public_key.read_bytes())
    install(args.policy, candidate)
    print('Installed verified data-only policy version', candidate['version'])
    print('Restart the proxy to apply consistently to new connections. No code, host scope or CA trust changed.')


if __name__ == '__main__': main()
