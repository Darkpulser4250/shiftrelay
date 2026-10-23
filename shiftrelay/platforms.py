"""Independent response filters for known, decrypted platform response schemas.

No app hooks, TLS unpinning, host discovery or media/DRM decryption is performed.
"""
from dataclasses import dataclass
import gzip
import json
import math
import re
import zlib
from urllib.parse import urlsplit

MAX_BODY = 2 * 1024 * 1024
MAX_NODES = 100000
MAX_DEPTH = 48


@dataclass(frozen=True)
class Adapter:
    hosts: tuple
    paths: tuple


ADAPTERS = {
    'youtube_player': Adapter(('youtubei.googleapis.com', 'www.youtube.com', 'm.youtube.com'),
                              ('/youtubei/v1/player',)),
    'instagram_timeline': Adapter(('i.instagram.com',), ('/api/v1/feed/timeline/',)),
    'facebook_graphql': Adapter(('graph.facebook.com', 'b-graph.facebook.com', 'www.facebook.com', 'web.facebook.com'),
                                ('/graphql', '/api/graphql/')),
}


@dataclass(frozen=True)
class Result:
    body: bytes
    units: int
    reason: str


def select(config, host, path, method):
    if config['mode'] == 'bypass' or method not in ('GET', 'POST'):
        return None
    if host not in config['inspect_hosts'] or host in config['bypass_hosts']:
        return None
    path = urlsplit(path).path
    for name in config.get('response_adapters', []):
        adapter = ADAPTERS[name]
        if host in adapter.hosts and path in adapter.paths:
            return name
    return None


def _object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('Duplicate JSON key')
        result[key] = value
    return result


def _constant(_):
    raise ValueError('Nonfinite JSON number')


def _bounded(value):
    stack = [(value, 0)]
    nodes = 0
    while stack:
        item, depth = stack.pop()
        nodes += 1
        if nodes > MAX_NODES or depth > MAX_DEPTH:
            raise ValueError('JSON complexity budget exceeded')
        if isinstance(item, float) and not math.isfinite(item):
            raise ValueError('Nonfinite JSON number')
        if isinstance(item, dict):
            stack.extend((child, depth + 1) for child in item.values())
        elif isinstance(item, list):
            stack.extend((child, depth + 1) for child in item)


def _decode(raw):
    value = json.loads(raw, object_pairs_hook=_object, parse_constant=_constant)
    _bounded(value)
    return value


def _encode(value):
    return json.dumps(value, ensure_ascii=False, separators=(',', ':'), allow_nan=False).encode('utf-8')


def _youtube(value):
    if not isinstance(value, dict):
        raise ValueError('Not a player response')
    details, status, stream = value.get('videoDetails'), value.get('playabilityStatus'), value.get('streamingData')
    if (not isinstance(details, dict) or not isinstance(details.get('videoId'), str) or not details['videoId']
            or not isinstance(status, dict) or status.get('status') != 'OK' or not isinstance(stream, dict)
            or not any(isinstance(stream.get(key), list) and stream[key] for key in ('formats', 'adaptiveFormats'))):
        raise ValueError('Unknown or unplayable player schema')
    keys = ('adPlacements', 'playerAds', 'adSlots')
    for key in keys:
        if key in value and (not isinstance(value[key], list) or any(not isinstance(item, dict) for item in value[key])):
            raise ValueError('Unknown ad-metadata shape')
    units = sum(len(value.get(key, [])) for key in keys)
    # Do not touch streamingData, media URLs, DRM/license fields or playback status.
    if units:
        for key in keys:
            value.pop(key, None)
    return units


def _instagram(value):
    if not isinstance(value, dict) or value.get('status') != 'ok' or not isinstance(value.get('feed_items'), list):
        raise ValueError('Unknown timeline schema')
    items = value['feed_items']
    if any(not isinstance(item, dict) for item in items):
        raise ValueError('Unknown timeline item')
    kept = []
    for item in items:
        media = item.get('media_or_ad')
        ad = False
        if isinstance(media, dict):
            identity = media.get('ad_id')
            valid_id = (type(identity) is int and identity > 0 or
                        isinstance(identity, str) and re.fullmatch(r'[0-9]{1,64}', identity) is not None)
            action = media.get('ad_action')
            metadata = media.get('ad_metadata')
            signal = (isinstance(action, str) and bool(action.strip()) or
                      isinstance(metadata, list) and bool(metadata) and all(isinstance(x, dict) for x in metadata))
            ad = valid_id and signal
        # A caption saying "sponsored", paid partnerships and ordinary posts stay.
        if not ad:
            kept.append(item)
    removed = len(items) - len(kept)
    if removed:
        value['feed_items'] = kept
        if type(value.get('num_results')) is int and value['num_results'] == len(items):
            value['num_results'] = len(kept)
    # Preserve pagination tokens and more_available to retain the next page path.
    return removed


def _sponsored(value):
    stack = [value]
    while stack:
        item = stack.pop()
        if isinstance(item, dict):
            if item.get('__typename') == 'SponsoredData':
                return True
            stack.extend(item.values())
        elif isinstance(item, list):
            stack.extend(item)
    return False


def _facebook(value):
    if not isinstance(value, dict) or value.get('errors'):
        raise ValueError('Unknown or error GraphQL response')
    data = value.get('data')
    if not isinstance(data, dict):
        return 0
    stack = [data]
    removed = 0
    while stack:
        item = stack.pop()
        if isinstance(item, dict):
            node = item.get('node')
            if isinstance(node, dict) and (item.get('category') == 'SPONSORED' or _sponsored(node)):
                del item['node']
                removed += 1
            # Edge cursors and page_info remain even when an ad node is removed.
            stack.extend(item.values())
        elif isinstance(item, list):
            stack.extend(item)
    return removed


def transform(name, raw):
    if name not in ADAPTERS or len(raw) > MAX_BODY:
        return Result(raw, 0, 'limit_or_unknown_adapter')
    try:
        if name != 'facebook_graphql':
            value = _decode(raw)
            units = {'youtube_player': _youtube, 'instagram_timeline': _instagram}[name](value)
            return Result(_encode(value) if units else raw, units, 'matched' if units else 'no_match')
        # Facebook may return newline-delimited incremental GraphQL records.
        prefix = b'for (;;);' if raw.startswith(b'for (;;);') else b''
        records = raw[len(prefix):].splitlines(keepends=True)
        if len(records) > 128:
            raise ValueError('Record budget exceeded')
        output, total = [], 0
        # Validate the complete response before committing any changes.
        for record in records:
            if not record.strip():
                output.append(record); continue
            value = _decode(record)
            units = _facebook(value)
            total += units
            ending = b'\r\n' if record.endswith(b'\r\n') else b'\n' if record.endswith(b'\n') else b''
            output.append(_encode(value) + ending if units else record)
        return Result(prefix + b''.join(output) if total else raw, total, 'matched' if total else 'no_match')
    except (ValueError, TypeError, RecursionError, OverflowError, UnicodeError):
        return Result(raw, 0, 'unknown_schema')


class BoundedResponse:
    """mitmproxy stream callback: finite buffering, then rewrite or byte passthrough."""
    def __init__(self, name, observe, report, encoding='identity', can_modify=lambda: True):
        self.name, self.observe, self.report = name, observe, report
        self.encoding, self.can_modify = encoding, can_modify
        self.parts = []
        self.size = 0
        self.passthrough = False

    def cancel(self):
        self.parts.clear()
        self.passthrough = True

    def __call__(self, chunk):
        if self.passthrough:
            return chunk
        if chunk:
            self.size += len(chunk)
            if self.size > MAX_BODY:
                self.passthrough = True
                original = b''.join(self.parts) + chunk
                self.parts.clear()
                self.report(0, 'oversize', False)
                return original
            self.parts.append(chunk)
            # An empty bytes event can encode a zero-length terminating chunk
            # in HTTP/1. Return no events while buffering instead.
            return []
        original = b''.join(self.parts)
        self.parts.clear()
        try:
            decoded = original
            if self.encoding != 'identity':
                decoder = zlib.decompressobj(31 if self.encoding == 'gzip' else 15)
                decoded = decoder.decompress(original, MAX_BODY + 1)
                if len(decoded) > MAX_BODY or decoder.unconsumed_tail or decoder.unused_data or not decoder.eof:
                    raise ValueError('Compressed body invalid or exceeds limit')
            result = transform(self.name, decoded)
            modify = not self.observe and self.can_modify() and result.units > 0
            output = result.body
            if modify and self.encoding != 'identity':
                output = gzip.compress(output, mtime=0) if self.encoding == 'gzip' else zlib.compress(output)
            self.report(result.units, result.reason, modify)
        except (ValueError, zlib.error):
            self.report(0, 'unknown_schema', False)
            modify = False
        self.passthrough = True
        return output if modify else original
