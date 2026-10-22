"""MIT core: validate the optional bridge's data-only public status, never its auth."""
import json
from pathlib import Path
import time

FIELDS = {'schema', 'adapter', 'mode', 'connected', 'ad_active', 'skip_enabled', 'volume_owned',
          'pending_restore', 'manual_override', 'reason', 'counters', 'updated_at'}
COUNTERS = {'ad_breaks', 'lower_requests', 'restore_requests', 'skip_requests', 'command_failures'}
REASONS = {'starting', 'recovery_pending', 'command_failed', 'recovery_device_mismatch',
           'volume_already_changed', 'manual_recovery_required', 'restore_requested',
           'volume_zero_requested', 'disconnected', 'observing', 'ready', 'manual_volume_override',
           'silence_budget_expired', 'events_stale', 'awaiting_pairing', 'connection_failed', 'volume_restore_confirmed'}


def read_native_status(directory, now=None):
    try:
        with (Path(directory) / 'youtube-tv.json').open('rb') as file:
            raw = file.read(8193)
        if len(raw) > 8192:
            raise ValueError('Too large')
        value = json.loads(raw)
        if not isinstance(value, dict) or set(value) != FIELDS:
            raise ValueError('Unknown fields')
        if type(value['schema']) is not int or value['schema'] != 1 or value['adapter'] != 'youtube_tv':
            raise ValueError('Unknown schema')
        if value['mode'] not in ('observe', 'assist') or value['reason'] not in REASONS:
            raise ValueError('Unknown status')
        for key in ('connected', 'skip_enabled', 'volume_owned', 'pending_restore', 'manual_override'):
            if type(value[key]) is not bool:
                raise ValueError('Boolean required')
        if value['ad_active'] is not None and type(value['ad_active']) is not bool:
            raise ValueError('Invalid ad state')
        counters = value['counters']
        if not isinstance(counters, dict) or set(counters) != COUNTERS or any(type(n) is not int or not 0 <= n < 2**63 for n in counters.values()):
            raise ValueError('Invalid counters')
        now = int(time.time()) if now is None else now
        if type(value['updated_at']) is not int or not 0 <= value['updated_at'] <= now + 5:
            raise ValueError('Invalid timestamp')
        value['stale'] = now - value['updated_at'] > 45
        if value['stale']:
            value['connected'] = False
        return value
    except (OSError, ValueError, TypeError):
        return None
