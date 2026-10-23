"""mitmproxy addon. Keep raw traffic in memory only; stream media bodies."""
import json
import os
from pathlib import Path
import tempfile
import time
from mitmproxy import ctx, http
from shiftrelay import policy
from shiftrelay.hls import rewrite
from shiftrelay.flow_identity import policy_host
from shiftrelay import platforms


class ShiftRelay:
    def __init__(self):
        self.path = Path(os.environ.get('SHIFTRELAY_POLICY', '/config/policy.json'))
        self.metrics_path = Path(os.environ.get('SHIFTRELAY_METRICS', '/status/metrics.json'))
        self.current = None
        self.mtime = None
        self.last_reload = 0
        self.last_write = 0
        self.counts = {'requests': 0, 'candidates': 0, 'blocked': 0, 'hls_segments_removed': 0, 'errors': 0}
        self.platform_counts = {name: {'eligible': 0, 'candidate_units': 0, 'modified_responses': 0,
                                      'removed_units': 0, 'unknown_schema': 0, 'unsupported_encoding': 0,
                                      'unsupported_format': 0, 'binary_unhandled': 0,
                                      'oversize': 0, 'buffer_budget': 0, 'no_match': 0}
                                for name in platforms.ADAPTERS}
        self.buffers = {}

    def running(self):
        self.reload(force=True)

    def reload(self, force=False):
        now = time.monotonic()
        if not force and now - self.last_reload < 1:
            return
        self.last_reload = now
        try:
            stamp = self.path.stat().st_mtime_ns
            if not force and stamp == self.mtime:
                return
            candidate = policy.load(self.path)
            ctx.options.update(allow_hosts=policy.tls_allow_hosts(candidate))
            self.current, self.mtime = candidate, stamp
        except (OSError, ValueError):
            self.counts['errors'] += 1
            # Preserve last known valid policy; cold-start failure refuses launch.
            if self.current is None:
                ctx.master.shutdown()
        self.write_metrics(force=True)

    def write_metrics(self, force=False):
        if not force and time.monotonic() - self.last_write < 2:
            return
        self.last_write = time.monotonic()
        snapshot = {**self.counts, 'updated_at': int(time.time()),
                    'mode': self.current['mode'] if self.current else 'invalid',
                    'policy_version': self.current['version'] if self.current else None,
                    'response_adapters': self.platform_counts}
        try:
            self.metrics_path.parent.mkdir(parents=True, exist_ok=True)
            fd, temporary = tempfile.mkstemp(dir=self.metrics_path.parent)
            with os.fdopen(fd, 'w') as f:
                json.dump(snapshot, f)
            os.replace(temporary, self.metrics_path)
        except OSError:
            pass

    def requestheaders(self, flow: http.HTTPFlow):
        self.reload()
        self.counts['requests'] += 1
        if self.current is None:
            return
        result = policy.decide(self.current, policy_host(flow), flow.request.path, flow.request.method)
        if result['action'] in ('observe', 'block'):
            self.counts['candidates'] += 1
        if result['action'] == 'block':
            self.counts['blocked'] += 1
            flow.response = http.Response.make(204, b'', {'Cache-Control': 'no-store', 'X-ShiftRelay': 'blocked'})
        else:
            flow.request.stream = True
        self.write_metrics()

    def responseheaders(self, flow: http.HTTPFlow):
        if flow.response is None or self.current is None:
            return
        typ = flow.response.headers.get('content-type', '').split(';')[0].strip().lower()
        host = policy_host(flow)
        name = platforms.select(self.current, host, flow.request.path, flow.request.method)
        if name and flow.response.status_code == 200 and not flow.response.headers.get('content-range'):
            counts = self.platform_counts[name]
            counts['eligible'] += 1
            encoding = flow.response.headers.get('content-encoding', 'identity').lower()
            if encoding not in ('identity', 'gzip', 'deflate') or typ not in ('application/json', 'text/json', 'application/x-javascript', 'application/javascript') or any(h in flow.response.headers for h in ('signature', 'signature-input')):
                # In particular, never guess Android's protobuf or Netflix MSL schema.
                reason = ('binary_unhandled' if 'protobuf' in typ else 'unsupported_encoding'
                          if encoding not in ('identity', 'gzip', 'deflate') else 'unsupported_format')
                counts[reason] += 1
                flow.response.stream = True
                self.write_metrics(force=True)
                return
            try:
                length = int(flow.response.headers.get('content-length', '0'))
            except ValueError:
                length = -1
            if not 0 <= length <= platforms.MAX_BODY:
                counts['oversize'] += 1
                flow.response.stream = True
                self.write_metrics(force=True)
                return
            if len(self.buffers) >= 4:
                counts['buffer_budget'] += 1
                flow.response.stream = True
                self.write_metrics(force=True)
                return
            observe = self.current['mode'] != 'filter'
            captured_policy, identity = self.current, id(flow)
            def report(units, reason, modified):
                self.buffers.pop(identity, None)
                counts['candidate_units'] += units
                if modified:
                    counts['modified_responses'] += 1
                    counts['removed_units'] += units
                elif reason in counts:
                    counts[reason] += 1
                self.write_metrics(force=True)
            if not observe:
                for header in ('content-length', 'etag', 'content-md5', 'digest', 'content-digest', 'repr-digest', 'last-modified', 'accept-ranges'):
                    flow.response.headers.pop(header, None)
                flow.response.headers['cache-control'] = 'no-store'
            buffer = platforms.BoundedResponse(name, observe, report, encoding,
                                                can_modify=lambda: self.current is captured_policy)
            self.buffers[identity] = buffer
            flow.response.stream = buffer
            return
        owned = host in self.current['owned_hls_hosts'] and host not in self.current['bypass_hosts']
        manifest = typ in ('application/vnd.apple.mpegurl', 'application/x-mpegurl')
        flow.metadata['shiftrelay_owned_manifest'] = owned and manifest and self.current['mode'] == 'filter'
        # Stream everything except small eligible owned-media manifests, capped below.
        if not flow.metadata['shiftrelay_owned_manifest']:
            flow.response.stream = True
        else:
            try:
                length = int(flow.response.headers.get('content-length', '-1'))
            except ValueError:
                length = -1
            if length < 0 or length > 131072 or flow.response.headers.get('content-encoding'):
                flow.response.stream = True
                flow.metadata['shiftrelay_owned_manifest'] = False

    def response(self, flow: http.HTTPFlow):
        if not flow.metadata.get('shiftrelay_owned_manifest') or flow.response is None or flow.response.raw_content is None:
            return
        if len(flow.response.raw_content) > 131072:
            return
        try:
            text = flow.response.raw_content.decode('utf-8')
            modified, removed = rewrite(text)
            if removed:
                flow.response.content = modified.encode('utf-8')
                for name in ('etag', 'content-md5', 'last-modified', 'content-range', 'accept-ranges'):
                    flow.response.headers.pop(name, None)
                flow.response.headers['cache-control'] = 'no-store'
                flow.response.headers['x-shiftrelay'] = 'owned-hls-rewritten'
                self.counts['hls_segments_removed'] += removed
                self.write_metrics(force=True)
        except UnicodeError:
            self.counts['errors'] += 1

    def error(self, flow):
        buffer = self.buffers.pop(id(flow), None)
        if buffer:
            buffer.cancel()
        self.counts['errors'] += 1
        self.write_metrics()

    def done(self):
        self.write_metrics(force=True)


addons = [ShiftRelay()]
