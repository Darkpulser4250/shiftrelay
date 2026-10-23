"""Strict, data-only filtering policy. Never execute downloaded code."""
import json
from pathlib import Path
import re
from urllib.parse import urlsplit

HOST = re.compile(r"(?=.{1,253}\Z)(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)*[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\Z")


def validate(value):
    required = {"schema", "version", "mode", "inspect_hosts", "bypass_hosts", "block_rules", "owned_hls_hosts"}
    if not isinstance(value, dict) or not required <= set(value) or set(value) - required - {'response_adapters'}:
        raise ValueError("Invalid policy keys")
    if type(value['schema']) is not int or value['schema'] != 1 or type(value['version']) is not int or value['version'] < 1:
        raise ValueError("Unsupported schema or version")
    if value['mode'] not in ('observe', 'filter', 'bypass'):
        raise ValueError("Invalid mode")
    for key in ('inspect_hosts', 'bypass_hosts', 'owned_hls_hosts'):
        hosts = value[key]
        if not isinstance(hosts, list) or len(hosts) > 100 or any(not isinstance(h, str) or not HOST.fullmatch(h) for h in hosts):
            raise ValueError("Hosts must be exact lowercase names, without ports or wildcards")
    if not set(value['owned_hls_hosts']) <= set(value['inspect_hosts']):
        raise ValueError("Owned HLS hosts must be inspected")
    adapters = value.get('response_adapters', [])
    allowed = {'youtube_player', 'instagram_timeline', 'facebook_graphql'}
    if not isinstance(adapters, list) or len(adapters) > 3 or any(not isinstance(x, str) or x not in allowed for x in adapters) or len(set(adapters)) != len(adapters):
        raise ValueError('Unknown or duplicate response adapter')
    if not isinstance(value['block_rules'], list) or len(value['block_rules']) > 500:
        raise ValueError("Too many rules")
    for rule in value['block_rules']:
        if not isinstance(rule, dict) or set(rule) != {'id', 'host', 'path'}:
            raise ValueError("Invalid block rule")
        if not isinstance(rule['id'], str) or not re.fullmatch(r'[a-z0-9_-]{1,64}', rule['id']):
            raise ValueError("Invalid rule id")
        if rule['host'] not in value['inspect_hosts']:
            raise ValueError("Block host must be explicitly inspected")
        path = rule['path']
        if not isinstance(path, str) or not path.startswith('/') or len(path) > 1024 or '?' in path or '#' in path or any(ord(c) < 32 for c in path):
            raise ValueError("Use an exact URL path, without query or fragment")
    return value


def load(path):
    raw = Path(path).read_bytes()
    if len(raw) > 131072:
        raise ValueError("Policy too large")
    return validate(json.loads(raw))


def tls_allow_hosts(policy):
    # A nonempty impossible match tunnels all TLS instead of intercepting everything.
    hosts = set(policy['inspect_hosts']) - set(policy['bypass_hosts'])
    if policy['mode'] == 'bypass':
        hosts.clear()
    return [r'^' + re.escape(h) + r'(?::[0-9]+)?$' for h in sorted(hosts)] or [r'(?!)']


def decide(policy, host, path, method):
    host = host.lower().rstrip('.')
    if policy['mode'] == 'bypass' or host in policy['bypass_hosts'] or host not in policy['inspect_hosts']:
        return {'action': 'pass', 'reason': 'bypass'}
    # Exact host + path; queries never enter logs or rule matching.
    rule = next((r for r in policy['block_rules'] if r['host'] == host and r['path'] == urlsplit(path).path), None)
    if rule and method in ('GET', 'HEAD'):
        return {'action': 'block' if policy['mode'] == 'filter' else 'observe', 'reason': rule['id']}
    return {'action': 'pass', 'reason': 'no_rule'}
