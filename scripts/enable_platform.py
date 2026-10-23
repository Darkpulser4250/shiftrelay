#!/usr/bin/env python3
"""Enable an explicitly selected server response filter; no phone/app modification."""
import argparse
import json
import os
from pathlib import Path
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from shiftrelay import platforms, policy

NAMES = {'youtube': 'youtube_player', 'instagram': 'instagram_timeline', 'facebook': 'facebook_graphql'}


def configure(current, names, mode):
    candidate = json.loads(json.dumps(current))
    candidate['version'] += 1
    candidate['mode'] = mode
    enabled = candidate.setdefault('response_adapters', [])
    for name in names:
        adapter = NAMES[name]
        if adapter not in enabled:
            enabled.append(adapter)
        for host in platforms.ADAPTERS[adapter].hosts:
            if host not in candidate['inspect_hosts']:
                candidate['inspect_hosts'].append(host)
    return policy.validate(candidate)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--platform', choices=NAMES, action='append', required=True)
    parser.add_argument('--policy', type=Path, default=ROOT / 'config/android.policy.json')
    parser.add_argument('--mode', choices=('observe', 'filter'), default='observe')
    parser.add_argument('--dry-run', action='store_true')
    args = parser.parse_args()
    current = policy.load(args.policy)
    candidate = configure(current, args.platform, args.mode)
    content = json.dumps(candidate, indent=2) + '\n'
    if args.dry_run:
        print(content, end=''); return
    fd, temporary = tempfile.mkstemp(dir=args.policy.parent)
    try:
        with os.fdopen(fd, 'w') as file:
            file.write(content); file.flush(); os.fsync(file.fileno())
        args.policy.with_suffix('.previous.json').write_bytes(args.policy.read_bytes())
        os.replace(temporary, args.policy)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
    print('Enabled response filters:', ', '.join(args.platform), '/ mode:', args.mode)
    print('Exact host scope is now:', ', '.join(candidate['inspect_hosts']))
    print('Existing host bypasses remain active. Restart the proxy to apply the policy.')
    print('These filters require decrypted supported responses; official app compatibility is unvalidated.')


if __name__ == '__main__':
    main()
