"""Owned-media test protocol, deliberately NOT a Netflix/Hulu manifest parser.

Only clear, complete, simple VOD playlists with our explicit markers are eligible.
Encrypted, live, byte-range, multi-variant and unknown-tag manifests pass unchanged.
"""
import math

START = '#EXT-X-SHIFTRELAY-AD-START'
END = '#EXT-X-SHIFTRELAY-AD-END'


def rewrite(text):
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if not lines or lines[0] != '#EXTM3U' or '#EXT-X-ENDLIST' not in lines or START not in lines:
        return text, 0
    if lines.count('#EXTM3U') != 1 or lines.count('#EXT-X-ENDLIST') != 1 or lines[-1] != '#EXT-X-ENDLIST':
        return text, 0
    safe = ('#EXT-X-VERSION:', '#EXT-X-TARGETDURATION:', '#EXT-X-MEDIA-SEQUENCE:', '#EXT-X-PLAYLIST-TYPE:', '#EXTINF:')
    exact = {'#EXTM3U', '#EXT-X-ENDLIST', '#EXT-X-DISCONTINUITY', START, END}
    if any(line.startswith('#') and line not in exact and not line.startswith(safe) for line in lines):
        return text, 0
    if '#EXT-X-PLAYLIST-TYPE:VOD' not in lines:
        return text, 0
    headers, kept = [], []
    ad = False
    pending = None
    discontinuity = False
    dropped = 0
    try:
        for line in lines[1:]:
            if line == START:
                if ad or pending is not None:
                    return text, 0
                ad = True
            elif line == END:
                if not ad or pending is not None:
                    return text, 0
                ad = False
                discontinuity = True
            elif line.startswith('#EXTINF:'):
                if pending is not None:
                    return text, 0
                duration = float(line.split(':', 1)[1].split(',')[0])
                if not math.isfinite(duration) or not 0 < duration <= 3600:
                    return text, 0
                pending = (line, duration)
            elif line == '#EXT-X-DISCONTINUITY':
                discontinuity = True
            elif line == '#EXT-X-ENDLIST':
                if line != lines[-1]:
                    return text, 0
            elif line.startswith('#'):
                if kept or pending is not None or ad:
                    return text, 0
                headers.append(line)
            else:
                if pending is None:
                    return text, 0
                if ad:
                    dropped += 1
                else:
                    kept.append((pending, line, discontinuity))
                    discontinuity = False
                pending = None
        if ad or pending is not None or not kept or not dropped:
            return text, 0
        result = ['#EXTM3U']
        for header in headers:
            if header.startswith('#EXT-X-TARGETDURATION:'):
                header = '#EXT-X-TARGETDURATION:' + str(math.ceil(max(p[0][1] for p in kept)))
            result.append(header)
        for pending, uri, discontinuity in kept:
            if discontinuity:
                result.append('#EXT-X-DISCONTINUITY')
            result.extend([pending[0], uri])
        result.append('#EXT-X-ENDLIST')
        return '\n'.join(result) + '\n', dropped
    except (ValueError, IndexError):
        return text, 0
